import logging
import os
import re
from urllib.parse import unquote

import backoff
from gremlin_python.driver import client, serializer
from gremlin_python.driver.protocol import GremlinServerError

cosmos_graph_primary_key = os.environ["COSMOS_GRAPH_PRIMARY_KEY"]

logging.basicConfig(
    format="%(process)s %(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)


def gremlin():
    return client.Client(
        "wss://Dependency-graph-cosmosdb-account.gremlin.cosmos.azure.com:443/",
        "g",
        username="/dbs/DependencyGraphDatabase/colls/DependencyGraph",
        password=cosmos_graph_primary_key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


# def drop_graph(gremlin_client):
#     callback = gremlin_client.submitAsync("g.E().drop()")
#     if callback.result() is not None:
#         logging.info("Dropped the graph")


def map_properties_to_gremlin_string(props):
    gremlin_string = ""
    bindings = {}
    for key, value in props.items():
        bindings[key] = key

        if isinstance(value, list):
            for index, val in enumerate(value):
                val_binding_key = f"{key}{index}"
                bindings[val_binding_key] = val
                gremlin_string += (
                    f".property(Cardinality.list, {key}, {val_binding_key})"
                )
        else:
            # handle it as a single value
            val_binding_key = f"{key}0"
            bindings[val_binding_key] = value
            gremlin_string += f".property(Cardinality.single, {key}, {val_binding_key})"

    return gremlin_string, bindings


def get_drop_statements(props):
    gremlin_string = ""
    bindings = {}

    for key, value in props.items():

        if isinstance(value, list):
            drop_binding_key = f"drop{key}"
            bindings[drop_binding_key] = key
            # we need to explode the value into a concatenation of gremlin strings
            gremlin_string += f".sideEffect(properties({drop_binding_key}).drop())"
        else:
            gremlin_string += ""

    return gremlin_string, bindings


def get_property_string(properties):
    bindings = {}
    if properties is None:
        return "", {}

    drop_gremlin_string, drop_bindings = get_drop_statements(properties)
    prop_gremlin_string, prop_bindings = map_properties_to_gremlin_string(properties)

    bindings.update(drop_bindings)
    bindings.update(prop_bindings)

    return drop_gremlin_string + prop_gremlin_string, bindings


def get_edges_by_vertex_and_label(gremlin_client, vertex_id, vertex_pk, label):
    gremlin_query = f"g.V('{vertex_id}').has('pk','{vertex_pk}')." f"outE(label)"

    return execute_gremlin_query(gremlin_client, gremlin_query, {"label": label})


def upsert_gremlin_vertex(gremlin_client, vertex_id, vertex_pk, properties, timestamp):
    bindings = {"timestamp": timestamp, "vertex_id": vertex_id, "vertex_pk": vertex_pk}

    properties["lastScanned"] = timestamp

    prop_gremlin_string, prop_bindings = get_property_string(properties)
    bindings.update(prop_bindings)

    gremlin_query = (
        f"g.V(vertex_id).has('pk',vertex_pk)."
        f"fold()."
        f"coalesce(unfold(),"
        f"addV().property(T.id, vertex_id).property('pk', vertex_pk).property('created', timestamp))"
        f"{prop_gremlin_string}"
    )

    result = execute_gremlin_query(gremlin_client, gremlin_query, bindings)
    logging.debug(f"Upserted {result}")


def cleanup_old_edges(
    gremlin_client, vertex_id, vertex_pk, timestamp_property, current_timestamp
):
    bindings = {
        "vertex_id": vertex_id,
        "vertex_pk": vertex_pk,
        "timestamp_property": timestamp_property,
        "current_timestamp": current_timestamp,
    }
    gremlin_query = f"g.V(vertex_id).has('pk',vertex_pk).bothE().has(timestamp_property).where(__.not(values(timestamp_property).is(current_timestamp))).drop()"
    result = execute_gremlin_query(gremlin_client, gremlin_query, bindings)
    logging.debug(f"Cleaned up edges: {result}")


def cleanup_old_outbound_neighbors(
    gremlin_client,
    vertex_id,
    vertex_pk,
    edge_label,
    timestamp_property,
    current_timestamp,
):
    bindings = {
        "vertex_id": vertex_id,
        "vertex_pk": vertex_pk,
        "edge_label": edge_label,
        "timestamp_property": timestamp_property,
        "current_timestamp": current_timestamp,
    }
    gremlin_query = f"g.V(vertex_id).has('pk',vertex_pk).out(edge_label).where(__.not(values(timestamp_property).is(current_timestamp))).drop()"
    result = execute_gremlin_query(gremlin_client, gremlin_query, bindings)
    logging.debug(f"Cleaned up neighbors: {result}")


def get_technologies(gremlin_client):
    gremlin_query = "g.V().has('type', 'technology')"

    result = execute_gremlin_query(gremlin_client, gremlin_query)

    technologies = []

    for technology in result:
        entry = {
            "id": technology["id"],
            "pk": technology["properties"]["pk"][0]["value"],
            "regexes": [
                re.compile(unquote(x["value"]))
                for x in technology["properties"]["regexes"]
            ],
        }
        technologies.append(entry)

    return technologies


def upsert_gremlin_edge(
    gremlin_client,
    edge_label,
    source_vertex_id,
    source_vertex_pk,
    destination_vertex_id,
    destination_vertex_pk,
    properties,
    timestamp,
):
    properties["lastScanned"] = timestamp

    edge_id = f"{source_vertex_id}.{source_vertex_pk}-{destination_vertex_id}.{destination_vertex_pk}"
    bindings = {
        "edge_id": edge_id,
        "source_vertex_id": source_vertex_id,
        "source_vertex_pk": source_vertex_pk,
        "destination_vertex_id": destination_vertex_id,
        "destination_vertex_pk": destination_vertex_pk,
        "edge_label": edge_label,
        "timestamp": timestamp,
    }
    prop_gremlin_string, prop_bindings = get_property_string(properties)
    bindings.update(prop_bindings)

    gremlin_query = (
        f"g.E(edge_id)."
        f"fold()."
        f"coalesce(unfold(),"
        f"g.V(source_vertex_id).has('pk', source_vertex_pk).as('source')."
        f"V(destination_vertex_id).has('pk', destination_vertex_pk)."
        f"addE(edge_label).from('source').property(T.id, edge_id).property('created', timestamp))"
        f"{prop_gremlin_string}"
    )

    result = execute_gremlin_query(gremlin_client, gremlin_query, bindings)
    logging.debug(f"Upserted edge {result}")


def get_vertex(gremlin_client, id, pk):
    gremlin_query = f"g.V(id).has('pk', pk)"
    bindings = {"id": id, "pk": pk}
    result = execute_gremlin_query(gremlin_client, gremlin_query, bindings)
    logging.debug(f"fetched vertex: {result}")
    return result[0] if len(result) > 0 else None


@backoff.on_exception(
    backoff.expo, (GremlinServerError, AttributeError), jitter=backoff.full_jitter, max_time=60
)
def execute_gremlin_query(gremlin_client, query, bindings=None):
    logging.debug(f"Running this Gremlin query: {query} with bindings: {bindings}")
    callback = gremlin_client.submitAsync(query, bindings)
    if callback.result() is None:
        logging.error(f"{query} failed to execute")
        raise Exception(f"Failed to query gremlin: {query}")

    return callback.result().all().result()
