import logging
import smtplib
from copy import deepcopy
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate
from io import StringIO
from os.path import basename

import pandas


def cross_join(left, right):
    new_rows = [] if right else left
    for left_row in left:
        for right_row in right:
            temp_row = deepcopy(left_row)
            for key, value in right_row.items():
                temp_row[key] = value
            new_rows.append(deepcopy(temp_row))
    return new_rows


def flatten_list(data):
    for elem in data:
        if isinstance(elem, list):
            yield from flatten_list(elem)
        else:
            yield elem


def json_to_dataframe(data_in):
    unflat_list_headings = [".repositories.languages"]

    def flatten_json(data, prev_heading=''):
        if isinstance(data, dict):
            rows = [{}]
            for key, value in data.items():
                rows = cross_join(rows, flatten_json(value, prev_heading + '.' + key))
        elif isinstance(data, list) and prev_heading not in unflat_list_headings:
            rows = []
            for i in range(len(data)):
                [rows.append(elem) for elem in flatten_list(flatten_json(data[i], prev_heading))]
        else:
            rows = [{prev_heading[1:]: data}]
        return rows

    return pandas.DataFrame(flatten_json(data_in))


def send_mail(send_from, send_to, subject, text, files=None,
              server="127.0.0.1"):
    assert isinstance(send_to, list)

    msg = MIMEMultipart()
    msg['From'] = send_from
    msg['To'] = COMMASPACE.join(send_to)
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = subject

    msg.attach(MIMEText(text))

    try:
        for f in files or []:
            if isinstance(f, str):
                with open(f, "rb") as fil:
                    filename = basename(f)
                    part = MIMEApplication(
                        fil.read(),
                        Name=filename
                    )
            else:
                filename = f["name"]
                part = MIMEApplication(
                    f["buffer"].read(),
                    Name=filename
                )
            # After the file is closed
            part['Content-Disposition'] = 'attachment; filename="%s"' % filename
            msg.attach(part)

        smtp = smtplib.SMTP(server)
        smtp.sendmail(send_from, send_to, msg.as_string())
        smtp.close()
    except Exception as e:
        logging.error("Failed to send email")
        logging.error(e, exc_info=True)


def report_to_csv_buffer(report):
    orgs = []


    for k,v in report.items():
        try:
            v['orgName'] = k
            orgs.append(v)
        except:
            pass

    df = json_to_dataframe(orgs)
    buffer = StringIO()
    df.to_csv(path_or_buf=buffer)
    return buffer
