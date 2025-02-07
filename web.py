import sqlite3
import json
from html import escape
from sanic import Sanic, html, empty
from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter


app = Sanic(__name__)

conn = sqlite3.connect("events")
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        exc_type VARCHAR(32),
        exc_repr VARCHAR(128),
        exc_args VARCHAR(64),
        exc_dict VARCHAR(256),
        line VARCHAR(128),
        lineno INTEGER,
        filename VARCHAR(128),
        code_name VARCHAR(128),
        frames TEXT,
        context TEXT
    )"""
)
cur.close()

GROUP_BY_COLS = ["exc_type", "exc_repr", "line", "filename", "code_name"]

with open("index.html") as f:
    TEMPLATE = f.read().format


def code(lines, first_lineno, lineno):
    return highlight("".join(lines), PythonLexer(), HtmlFormatter(
        linenos=True,
        linenostart=first_lineno,
        style="monokai",
    )).replace(
        f'<span class="normal">{lineno}</span>',
        f'<span class="normal selected-line">{lineno}</span>',
    )


def highlight_value(value):
    if isinstance(value, (int, float, bool)):
        return f'<span class="mi">{value}</span>'
    elif isinstance(value, str):
        return f'<span class="sd">&quot;{escape(value)}&quot;</span>'
    elif value is None:
        return f'<span class="kc">None</span>'
    elif isinstance(value, dict):
        if "_penntry_class" in value:
            if value["_penntry_class"] == "_penntry_tuple":
                if value["_penntry_values"]:
                    return f'<span class="kc>{", ".join(highlight_value(item) for item in value["_penntry_values"])}</span>'
                else:
                    return f'<span class="kc">()</span>'
            elif value["_penntry_class"] == "type":
                return f'<span class="fm">{escape(value["_penntry_repr"])}</span>'
            elif value["_penntry_class"] == "module":
                return f'<span class="bp">module</span> <span class="fm">{escape(value["_penntry_repr"])}</span>'
            elif "_penntry_vars" in value:
                return f"""<details>
                    <summary>
                    <kbd>{value['_penntry_class']} object {value['_penntry_repr']}</kbd>
                    </summary>
                    {highlight_value(value["_penntry_vars"])}
                    </details>
                """
            else:
                return f"<kbd>{value['_penntry_class']} object {value['_penntry_repr']}</kbd>"
        if not value:
            return '<span class="kc">{}</span>'
        return locals_table(value)
    elif isinstance(value, list):
        if not value:
            return '<span class="kc">[]</span>'
        return locals_table({f"#{i}": item for i, item in enumerate(value)})
    else:
        return "WAT"


def locals_table(locals):
    result = ['<table>']
    for name, value in locals.items():
        result.append(f'<tr><td>{name}</td><td class="code">{highlight_value(value)}</td></tr>')
    result.append("</table>")
    return "".join(result)


def format_frame(frame):
    return f"""<details>
    <summary><tt>{escape(frame["name"])}</tt> <small>in {frame["filename"]}:L{frame["lineno"]}</small></summary>
    {code(frame["lines"], frame["first_lineno"], frame["lineno"])}
    {locals_table(frame["locals"])}
    </details>"""


def make_siblings(siblings):
    if not siblings:
        return ""
    result = [f"<details><summary><strong>{len(siblings)} other occurrences</strong></summary>"]
    for sibling in siblings:
        result.append(f'<a role="button" href="/events/{sibling["id"]}">{sibling["timestamp"]}</a>')
    result.append("</details>")
    return "".join(result)


def event_list_item(event):
    return f"""<article
        hx-get="/events/{event["id"]}"
        hx-target="main"
        hx-select="main"
        hx-swap="outerHTML"
        hx-push-url="true"
        class="clickable"
    >
        <header><strong><tt>{event["exc_repr"]}</tt></strong> <small>in {escape(event["code_name"])} ({event["filename"]}:L{event["lineno"]})</small>
        <small class="ts">{event["timestamp"]}</small>
        </header>
        <kbd>{event["line"]}</kbd>
        <footer><em>{event["count"]} occurrences</em></footer>
    </article>"""


def event_detail(event, siblings):
    ctx = json.loads(event["context"])
    return f"""
        <article>
        <header><strong>{event["exc_repr"]}</strong> <small>in {escape(event["code_name"])} ({event["filename"]}:L{event["lineno"]})</small>
        <small class="ts">{event["timestamp"]}</small>
        </header>
        {"".join(format_frame(frame) for frame in reversed(json.loads(event["frames"])))}
        </article>
        <h3>Context</h3>
        {locals_table(ctx) if ctx else ""}
        {make_siblings(siblings)}
    """


@app.get("/events/<event_id>")
async def get_event(request, event_id: int):
    cur = conn.cursor()
    event = cur.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    siblings = cur.execute(f"""
        SELECT id, timestamp
        FROM events
        WHERE {" AND ".join(f"{col} = ?" for col in GROUP_BY_COLS)}
            AND id <> ?
        ORDER BY id DESC
        """,
        (
            *(event[col] for col in GROUP_BY_COLS),
            event["id"],
        )
    ).fetchall()
    return html(TEMPLATE(event_detail(event, siblings)))
    # return html(TEMPLATE(f"{event:details}"))


@app.get("/")
async def index(request):
    cur = conn.cursor()
    events = cur.execute(f"""
        SELECT *, MAX(id) AS id, COUNT(1) AS count
        FROM events
        GROUP BY {", ".join(GROUP_BY_COLS)}
        ORDER BY id DESC
    """).fetchall()
    return html(TEMPLATE(
        "".join(f"{event_list_item(event)}" for event in events)
    ))


@app.post("/event")
async def submit_event(request):
    data = request.json
    last_frame = data["frames"][-1]
    code_name = last_frame["name"]
    filename = last_frame["filename"]
    line = last_frame["lines"][last_frame["lineno"] - last_frame["first_lineno"]]
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO events (exc_type, exc_repr, exc_args, exc_dict, line, lineno, filename, code_name, frames, context)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["exception"][0],
            data["exception"][1],
            str(data["exception"][2]),
            str(data["exception"][3]),
            line,
            last_frame["lineno"],
            filename,
            code_name,
            json.dumps(data["frames"]),
            json.dumps(data["context"]),
        ))
    conn.commit()
    return empty()
