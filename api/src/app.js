var express = require("express");
var app = express();
const spawn = require('await-spawn')

app.listen(3000, () => {
    console.log("Server running on port 3000");
});

function execShellCommand(cmd) {
    const exec = require('child_process').exec;
    return new Promise((resolve, reject) => {
        exec(cmd, {
            env: {
                PYTHONPATH: "/var/aaavang/pip"
            }
        }, (error, stdout, stderr) => {
            if (error) {
                console.warn(error);
            }
            resolve(stdout ? stdout : stderr);
        });
    });
}

app.get("/scan/:org/:repo", async (req, res, next) => {
    var {org, repo} = req.params

    if (!org.match(/^[A-Za-z0-9_.-]+$/g)) {
        res.statusCode = 400
        res.send("bad org")
        return
    }

    if (!repo.match(/^[A-Za-z0-9_.-]+$/g)) {
        res.statusCode = 400
        res.send("bad repo")
        return
    }
    console.info(`scanning ${org}/${repo}`)

    var DependencyProcessCount = 0

    try {
        DependencyProcessCount = (await execShellCommand("ps -ef | grep ADHOC | grep -v grep | wc -l")).toString().trim()
        console.log('ps result', DependencyProcessCount)
    } catch (e) {
        console.error(e.stderr.toString())
    }
    console.log(`${DependencyProcessCount} number of scans running`)

    if (DependencyProcessCount > 15) {
        console.warn("more than 15 scans running, returning")
        res.statusCode = 429
        res.set('Content-Type', 'text/html')
        res.send(`too many scans running.  Try again later`)
        return
    }

    try {
        let output = (await execShellCommand(`${process.env.PYTHON_PATH || 'python'} Dependency.py ${org} ${repo} ADHOC 2>&1`)).toString()

        console.log(`${org}/${repo} Dependency raw output:`, output)

        output = output.split('\n').filter(s => (s.includes("valid")
            || s.includes("Exception when")
            || s.includes("bad ")
            || s.includes("No Dependencyfile found")
            || s.includes("No vitals.yaml found"))
            && !s.includes("DEBUG")).map(s => s + '<br>').join('')

        console.log(`${org}/${repo} Dependency output:`, output)

        res.set('Content-Type', 'text/html')
        res.statusCode = 200
        res.send(output)
    } catch (e) {
        console.error(e)
    }

    res.statusCode = 500
    res.send()
});