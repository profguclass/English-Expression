import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import json
from typing import List, Optional

DB_PATH = "memorizer.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # Create a minimal table if missing, then add columns if needed (migration)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY,
        front TEXT NOT NULL,
        back TEXT NOT NULL,
        tags TEXT,
        created_at TEXT,
        interval REAL DEFAULT 1,
        ease REAL DEFAULT 2.5,
        repetitions INTEGER DEFAULT 0,
        due_at TEXT
    )
    ''')
    # Ensure newer columns exist (safe ALTER TABLE ADD COLUMN)
    optional_cols = {
        'etymology': 'TEXT',
        'synonyms': 'TEXT',
        'antonyms': 'TEXT',
        'examples': 'TEXT',
        'translations': 'TEXT',
        'usage': 'TEXT',
        'pronunciation': 'TEXT',
        'context': 'TEXT'
    }
    for col, typ in optional_cols.items():
        try:
            cur.execute(f"ALTER TABLE entries ADD COLUMN {col} {typ}")
        except Exception:
            # column probably exists
            pass
    conn.commit()
    conn.close()

def add_entry(front: str, back: str, etymology: Optional[str] = None, synonyms: Optional[List[str]] = None, antonyms: Optional[List[str]] = None, examples: Optional[List[str]] = None, translations: Optional[List[str]] = None, usage: Optional[str] = None, pronunciation: Optional[dict] = None, context: Optional[str] = None, tags: Optional[List[str]] = None):
    tags_s = ",".join(tags) if tags else ""
    syn_s = ",".join(synonyms) if synonyms else ""
    ant_s = ",".join(antonyms) if antonyms else ""
    examples_s = json.dumps(examples or [])
    translations_s = json.dumps(translations or [])
    pron_s = json.dumps(pronunciation or {})
    now = datetime.utcnow().isoformat()
    due = now
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO entries (front, back, etymology, synonyms, antonyms, examples, translations, usage, pronunciation, context, tags, created_at, due_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (front, back, etymology or "", syn_s, ant_s, examples_s, translations_s, usage or "", pron_s, context or "", tags_s, now, due),
    )
    conn.commit()
    conn.close()

def update_entry_srs(entry_id: int, quality: int):
    """SM-2 like update"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    interval = row["interval"]
    ease = row["ease"]
    reps = row["repetitions"]
    now = datetime.utcnow()

    if quality >= 3:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = max(1, interval * ease)
        reps += 1
        # ease factor update
        ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        if ease < 1.3:
            ease = 1.3
    else:
        reps = 0
        interval = 1

    due = (now + timedelta(days=round(interval))).isoformat()
    cur.execute(
        "UPDATE entries SET interval = ?, ease = ?, repetitions = ?, due_at = ? WHERE id = ?",
        (interval, ease, reps, due, entry_id),
    )
    conn.commit()
    conn.close()

def list_entries(query: Optional[str] = None, tag: Optional[str] = None, due_only: bool = False):
    conn = get_conn()
    cur = conn.cursor()
    sql = "SELECT * FROM entries"
    clauses = []
    params = []
    if due_only:
        clauses.append("datetime(due_at) <= datetime(?)")
        params.append(datetime.utcnow().isoformat())
    if query:
        clauses.append("(front LIKE ? OR back LIKE ?)")
        p = f"%{query}%"
        params.extend([p, p])
    if tag:
        clauses.append("tags LIKE ?")
        params.append(f"%{tag}%")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY datetime(due_at) ASC"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_random_wrong_answers(entry_id: int, correct_answer: str, count: int = 3):
    """Get random wrong answers (meanings) from other entries for multiple choice."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT back FROM entries WHERE id != ? AND back IS NOT NULL AND back != '' ORDER BY RANDOM() LIMIT ?", (entry_id, count))
    rows = cur.fetchall()
    conn.close()
    return [r['back'] for r in rows]

def import_json_lines(text: str):
    """Import JSON from either a single JSON object, a JSON array, or multiple JSON objects/lines.
    Returns number of items added.
    """
    text = (text or "").strip()
    if not text:
        return 0
    objs = []
    # Try parse whole text as JSON (object or array)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            objs = data
        elif isinstance(data, dict):
            objs = [data]
    except Exception:
        # Fallback: try parse line-by-line as JSON objects
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for line in lines:
            try:
                objs.append(json.loads(line))
            except Exception:
                # try to accumulate balanced braces blocks (naive) - skip if invalid
                continue
    added = 0
    for obj in objs:
        try:
            front = obj.get("front") or obj.get("word") or obj.get("question")
            back = obj.get("back") or obj.get("meaning") or obj.get("answer")
            etymology = obj.get("etymology")
            synonyms = obj.get("synonyms")
            antonyms = obj.get("antonyms")
            examples = obj.get("examples")
            translations = obj.get("translations")
            usage = obj.get("usage")
            pronunciation = obj.get("pronunciation")
            context = obj.get("context")
            tags = obj.get("tags")
            # normalize fields
            if isinstance(synonyms, str):
                synonyms = [s.strip() for s in synonyms.split(",") if s.strip()]
            if isinstance(antonyms, str):
                antonyms = [s.strip() for s in antonyms.split(",") if s.strip()]
            if front and back:
                add_entry(front, back, etymology=etymology, synonyms=synonyms, antonyms=antonyms, examples=examples, translations=translations, usage=usage, pronunciation=pronunciation, context=context, tags=tags)
                added += 1
        except Exception:
            continue
    return added

# Streamlit UI
st.set_page_config(page_title="Memorizer", layout="wide")
init_db()

st.title("Memorizer : English → Korean Study App")

sidebar = st.sidebar
mode = sidebar.selectbox("Mode", ["Browse & Edit", "Add / Import", "Review (SRS)", "Stats"])

if mode == "Add / Import":
    st.header("Import JSON lines")
    st.info('Accepts a single JSON object, a JSON array, or multiple JSON objects. Example object: {"word":"...","pronunciation":{"us":"...","uk":"..."},"meaning":"...","etymology":"...","synonyms":["..."],"antonyms":["..."],"examples":["..."],"translations":["..."],"context":"...","tags":["..."]}')
    js = st.text_area("Paste JSON here (object or array)")
    if st.button("Import JSON"):
        n = import_json_lines(js)
        st.success(f"Imported {n} items")

    st.markdown("---")
    st.header("Add a new item")
    with st.form("add_form"):
        front = st.text_input("Word (English)")
        back = st.text_area("Meaning (Korean / Notes)")
        etymology = st.text_area("Etymology (optional)")
        synonyms = st.text_input("Synonyms (comma separated)")
        antonyms = st.text_input("Antonyms (comma separated)")
        st.markdown("Examples (up to 3)")
        ex1 = st.text_input("Example 1")
        tr1 = st.text_input("Translation 1 (Korean)")
        ex2 = st.text_input("Example 2")
        tr2 = st.text_input("Translation 2 (Korean)")
        ex3 = st.text_input("Example 3")
        tr3 = st.text_input("Translation 3 (Korean)")
        usage = st.text_input("Usage / Context")
        st.markdown("Pronunciation (optional)")
        pron_us = st.text_input("US pronunciation (e.g. /ˈfiːnətaɪp/")
        pron_uk = st.text_input("UK pronunciation (e.g. /ˈfiːnəʊtaɪp/")
        context = st.text_area("Context (where the word is used)")
        tags = st.text_input("Tags (comma separated)")
        submitted = st.form_submit_button("Add")
        if submitted:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            syn_list = [s.strip() for s in synonyms.split(",") if s.strip()]
            ant_list = [s.strip() for s in antonyms.split(",") if s.strip()]
            examples = [e for e in [ex1, ex2, ex3] if e.strip()]
            translations = [t for t in [tr1, tr2, tr3] if t.strip()]
            pron = {}
            if pron_us.strip():
                pron['us'] = pron_us.strip()
            if pron_uk.strip():
                pron['uk'] = pron_uk.strip()
            add_entry(front.strip(), back.strip(), etymology=etymology.strip(), synonyms=syn_list, antonyms=ant_list, examples=examples, translations=translations, usage=usage.strip(), pronunciation=pron, context=context.strip(), tags=tag_list)
            st.success("Added")

elif mode == "Browse & Edit":
    st.header("Browse entries")
    q = st.text_input("Search")
    tag = st.text_input("Filter tag")
    rows = list_entries(query=q or None, tag=tag or None)
    for r in rows:
        cols = st.columns([3, 5, 2, 1])
        with cols[0]:
            st.markdown(f"**{r['front']}**")
            st.write(r["back"])
            if r['etymology']:
                st.write(f"Etymology: {r['etymology']}")
            # pronunciation
            try:
                pron = json.loads(r['pronunciation'] or '{}')
            except Exception:
                pron = {}
            if pron.get('us') or pron.get('uk'):
                st.write(f"Pronunciation: {pron.get('us','')}{' / ' if pron.get('us') and pron.get('uk') else ''}{pron.get('uk','')}")
        with cols[1]:
            st.write(f"Synonyms: {r['synonyms']}")
            st.write(f"Antonyms: {r['antonyms']}")
            try:
                exs = json.loads(r['examples'] or '[]')
                trs = json.loads(r['translations'] or '[]')
            except Exception:
                exs = []
                trs = []
            for i, ex in enumerate(exs):
                tr = trs[i] if i < len(trs) else ""
                st.write(f"Example {i+1}: {ex}")
                if tr:
                    st.write(f" → {tr}")
            st.write(f"Usage / Context: {r['context'] or ''}")
            st.write(f"Tags: {r['tags']}")
            st.write(f"Due: {r['due_at']}")
        with cols[2]:
            if st.button(f"Edit {r['id']}"):
                with st.form(f"edit_{r['id']}"):
                    new_front = st.text_input("Word", value=r['front'])
                    new_back = st.text_area("Meaning", value=r['back'])
                    new_etym = st.text_area("Etymology", value=r['etymology'] or "")
                    new_syn = st.text_input("Synonyms (comma)", value=r['synonyms'] or "")
                    new_ant = st.text_input("Antonyms (comma)", value=r['antonyms'] or "")
                    exs = json.loads(r['examples'] or '[]') if r['examples'] else []
                    trs = json.loads(r['translations'] or '[]') if r['translations'] else []
                    ne1 = st.text_input("Example 1", value=exs[0] if len(exs)>0 else "")
                    nt1 = st.text_input("Translation 1", value=trs[0] if len(trs)>0 else "")
                    ne2 = st.text_input("Example 2", value=exs[1] if len(exs)>1 else "")
                    nt2 = st.text_input("Translation 2", value=trs[1] if len(trs)>1 else "")
                    ne3 = st.text_input("Example 3", value=exs[2] if len(exs)>2 else "")
                    nt3 = st.text_input("Translation 3", value=trs[2] if len(trs)>2 else "")
                    new_usage = st.text_input("Usage", value=r['usage'] or "")
                    new_tags = st.text_input("Tags", value=r['tags'])
                    if st.form_submit_button("Save"):
                        syn_list = [s.strip() for s in (new_syn or "").split(",") if s.strip()]
                        ant_list = [s.strip() for s in (new_ant or "").split(",") if s.strip()]
                        examples = [e for e in [ne1, ne2, ne3] if e.strip()]
                        translations = [t for t in [nt1, nt2, nt3] if t.strip()]
                        conn = get_conn()
                        cur = conn.cursor()
                        cur.execute(
                            "UPDATE entries SET front=?, back=?, etymology=?, synonyms=?, antonyms=?, examples=?, translations=?, usage=?, tags=? WHERE id=?",
                            (new_front, new_back, new_etym, ",".join(syn_list), ",".join(ant_list), json.dumps(examples), json.dumps(translations), new_usage, new_tags, r['id']),
                        )
                        conn.commit()
                        conn.close()
                        st.success("Saved")
            if st.button(f"Delete {r['id']}"):
                delete_entry(r['id'])
                st.experimental_rerun()

elif mode == "Review (SRS)":
    st.header("Review — Multiple Choice Quiz")
    due_items = list_entries(due_only=True)
    if not due_items:
        st.info("No items due. Good job!")
    else:
        import random
        # Shuffle due items
        items_list = list(due_items)
        random.shuffle(items_list)
        
        for r in items_list[:5]:  # Show max 5 items per session
            st.markdown(f"---")
            try:
                exs = json.loads(r['examples'] or '[]')
            except Exception:
                exs = []
            
            if not exs:
                st.write(f"(No examples for {r['front']})")
                continue
            
            # Pick a random example
            example_text = random.choice(exs)
            meaning = r['back']
            
            st.markdown(f"**Example:** _{example_text}_")
            st.markdown(f"**Question:** What does **{r['front']}** mean in this context?")
            
            # Get 3 random wrong answers
            wrong_answers = get_random_wrong_answers(r['id'], meaning, 3)
            
            # Create 4-choice quiz (limit to first 3 wrong answers to avoid duplicates)
            choices = [meaning] + wrong_answers[:3]
            random.shuffle(choices)
            
            # Multiple choice with radio buttons
            selected = st.radio(
                f"Choose the correct meaning (ID: {r['id']})",
                options=choices,
                key=f"choice_{r['id']}"
            )
            
            if st.button(f"Submit answer", key=f"submit_{r['id']}"):
                if selected == meaning:
                    st.success("✓ Correct!")
                    update_entry_srs(r['id'], 5)  # quality=5 for correct answer
                else:
                    st.error(f"✗ Incorrect. The correct answer is: {meaning}")
                    update_entry_srs(r['id'], 0)  # quality=0 for wrong answer
                st.experimental_rerun()

elif mode == "Stats":
    st.header("Statistics")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM entries")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM entries WHERE datetime(due_at) <= datetime(?)", (datetime.utcnow().isoformat(),))
    due = cur.fetchone()[0]
    st.write(f"Total items: {total}")
    st.write(f"Due now: {due}")

st.sidebar.markdown("---")
st.sidebar.write("Run: streamlit run app.py")
