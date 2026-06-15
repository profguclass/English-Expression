import streamlit as st
import gspread
from datetime import datetime, timedelta
import json
import re
from typing import List, Optional
import random

try:
    from google.oauth2.service_account import Credentials as GoogleCredentials
except ImportError:
    GoogleCredentials = None

from oauth2client.service_account import ServiceAccountCredentials

SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def get_gsheet():
    """Connect to Google Sheet using Streamlit secrets."""
    try:
        creds_secret = st.secrets["google_service_account"]
        if isinstance(creds_secret, str):
            creds_secret = creds_secret.strip()
            try:
                creds_secret = json.loads(creds_secret)
            except json.JSONDecodeError:
                # Try to recover from a quoted/escaped JSON string or TOML multiline string
                try:
                    import ast
                    creds_secret = ast.literal_eval(creds_secret)
                except Exception:
                    def _escape_json_string_newlines(text):
                        escaped = False
                        in_string = False
                        result = []
                        for ch in text:
                            if ch == '"' and not escaped:
                                in_string = not in_string
                            if in_string and ch == '\n' and not escaped:
                                result.append('\\n')
                                continue
                            if in_string and ch == '\r' and not escaped:
                                result.append('\\n')
                                continue
                            if ch == '\\' and not escaped:
                                escaped = True
                                result.append(ch)
                                continue
                            if escaped:
                                escaped = False
                            result.append(ch)
                        return ''.join(result)

                    fixed_text = _escape_json_string_newlines(creds_secret)
                    try:
                        creds_secret = json.loads(fixed_text)
                    except Exception:
                        # Fallback: explicitly escape raw newlines in private_key value
                        match = re.search(r'("private_key"\s*:\s*")(.+?)("\s*,)', creds_secret, re.DOTALL)
                        if match:
                            escaped_key = match.group(2).replace('\\n', '\\\\n').replace('\n', '\\\\n').replace('\r', '\\\\n')
                            creds_secret = creds_secret[:match.start(2)] + escaped_key + creds_secret[match.end(2):]
                            creds_secret = json.loads(creds_secret)
                        else:
                            raise ValueError("google_service_account secret is not valid JSON")
        if not isinstance(creds_secret, dict):
            raise ValueError("google_service_account must be JSON object or JSON string")

        try:
            gc = gspread.service_account_from_dict(creds_secret, scopes=SCOPE)
        except AttributeError:
            if GoogleCredentials is not None:
                creds = GoogleCredentials.from_service_account_info(creds_secret, scopes=SCOPE)
            else:
                creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_secret, SCOPE)
            gc = gspread.authorize(creds)

        sheet = gc.open_by_key(st.secrets["google_sheet_id"]).sheet1
        return sheet
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {type(e).__name__}: {e}")
        st.error("Make sure google_service_account is the full JSON object and that google_sheet_id is correct.")
        return None

def init_sheet(sheet):
    """Initialize sheet with headers if empty."""
    try:
        if sheet.cell(1, 1).value is None:
            headers = ['id', 'front', 'back', 'etymology', 'synonyms', 'antonyms', 'examples', 
                      'translations', 'usage', 'pronunciation', 'context', 'tags', 'created_at',
                      'interval', 'ease', 'repetitions', 'due_at']
            sheet.insert_row(headers, 1)
    except Exception as e:
        st.error(f"Failed to initialize sheet: {e}")

def get_all_entries(sheet):
    """Fetch all entries from Google Sheet."""
    try:
        data = sheet.get_all_records()
        return data
    except Exception as e:
        st.error(f"Failed to fetch entries: {e}")
        return []

def add_entry(sheet, front: str, back: str, etymology: Optional[str] = None, 
              synonyms: Optional[List[str]] = None, antonyms: Optional[List[str]] = None,
              examples: Optional[List[str]] = None, translations: Optional[List[str]] = None,
              usage: Optional[str] = None, pronunciation: Optional[dict] = None,
              context: Optional[str] = None, tags: Optional[List[str]] = None):
    """Add new entry to Google Sheet."""
    try:
        all_entries = get_all_entries(sheet)
        new_id = max([int(e.get('id', 0)) for e in all_entries], default=0) + 1
        now = datetime.utcnow().isoformat()
        
        row = [
            str(new_id), front, back,
            etymology or '', ','.join(synonyms) if synonyms else '', ','.join(antonyms) if antonyms else '',
            json.dumps(examples or []), json.dumps(translations or []), usage or '', 
            json.dumps(pronunciation or {}), context or '', ','.join(tags) if tags else '',
            now, '1', '2.5', '0', now
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"Failed to add entry: {e}")
        return False

def update_entry_srs(sheet, entry_id: int, quality: int):
    """Update SRS score (SM-2 algorithm)."""
    try:
        all_entries = get_all_entries(sheet)
        for idx, entry in enumerate(all_entries, start=2):  # Row 2 onwards (header at 1)
            if int(entry.get('id', 0)) == entry_id:
                interval = float(entry.get('interval', 1))
                ease = float(entry.get('ease', 2.5))
                reps = int(entry.get('repetitions', 0))
                now = datetime.utcnow()
                
                if quality >= 3:
                    if reps == 0:
                        interval = 1
                    elif reps == 1:
                        interval = 6
                    else:
                        interval = max(1, interval * ease)
                    reps += 1
                    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
                    if ease < 1.3:
                        ease = 1.3
                else:
                    reps = 0
                    interval = 1
                
                due = (now + timedelta(days=round(interval))).isoformat()
                sheet.update_cell(idx, 14, interval)  # interval
                sheet.update_cell(idx, 15, ease)      # ease
                sheet.update_cell(idx, 16, reps)      # repetitions
                sheet.update_cell(idx, 17, due)       # due_at
                return True
        return False
    except Exception as e:
        st.error(f"Failed to update SRS: {e}")
        return False

def delete_entry(sheet, entry_id: int):
    """Delete entry from Google Sheet."""
    try:
        all_entries = get_all_entries(sheet)
        for idx, entry in enumerate(all_entries, start=2):
            if int(entry.get('id', 0)) == entry_id:
                sheet.delete_rows(idx)
                return True
        return False
    except Exception as e:
        st.error(f"Failed to delete entry: {e}")
        return False

def list_entries(sheet, query: Optional[str] = None, tag: Optional[str] = None, due_only: bool = False):
    """List entries with optional filtering."""
    try:
        entries = get_all_entries(sheet)
        now = datetime.utcnow().isoformat()
        
        filtered = []
        for entry in entries:
            # Filter by due date
            if due_only and entry.get('due_at', '') > now:
                continue
            # Filter by query
            if query:
                if query.lower() not in entry.get('front', '').lower() and query.lower() not in entry.get('back', '').lower():
                    continue
            # Filter by tag
            if tag:
                if tag not in entry.get('tags', ''):
                    continue
            filtered.append(entry)
        
        # Sort by due_at
        filtered.sort(key=lambda e: e.get('due_at', ''))
        return filtered
    except Exception as e:
        st.error(f"Failed to list entries: {e}")
        return []

def get_random_wrong_answers(sheet, entry_id: int, count: int = 3):
    """Get random wrong answers from other entries."""
    try:
        entries = get_all_entries(sheet)
        backs = [e.get('back', '') for e in entries if str(e.get('id', 0)) != str(entry_id) and e.get('back')]
        random.shuffle(backs)
        return backs[:count]
    except Exception as e:
        st.error(f"Failed to get wrong answers: {e}")
        return []

def import_json_lines(sheet, text: str):
    """Import JSON entries."""
    text = (text or '').strip()
    if not text:
        return 0
    
    objs = []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            objs = data
        elif isinstance(data, dict):
            objs = [data]
    except Exception:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for line in lines:
            try:
                objs.append(json.loads(line))
            except Exception:
                continue
    
    added = 0
    for obj in objs:
        try:
            front = obj.get("front") or obj.get("word") or obj.get("question")
            back = obj.get("back") or obj.get("meaning") or obj.get("answer")
            if front and back:
                add_entry(sheet, front, back,
                         etymology=obj.get("etymology"),
                         synonyms=obj.get("synonyms"),
                         antonyms=obj.get("antonyms"),
                         examples=obj.get("examples"),
                         translations=obj.get("translations"),
                         usage=obj.get("usage"),
                         pronunciation=obj.get("pronunciation"),
                         context=obj.get("context"),
                         tags=obj.get("tags"))
                added += 1
        except Exception:
            continue
    return added

# Streamlit UI
st.set_page_config(page_title="Memorizer (Google Sheets)", layout="wide")

sheet = get_gsheet()
if sheet is None:
    st.stop()

init_sheet(sheet)

st.title("Memorizer — English Study App (Cloud)")

sidebar = st.sidebar
mode = sidebar.selectbox("Mode", ["Browse & Edit", "Add / Import", "Review (SRS)", "Stats"])

if mode == "Add / Import":
    st.header("Import JSON lines")
    st.info('Accepts a single JSON object or array')
    js = st.text_area("Paste JSON here")
    if st.button("Import JSON"):
        n = import_json_lines(sheet, js)
        st.success(f"Imported {n} items")
        st.cache_resource.clear()

    st.markdown("---")
    st.header("Add a new item")
    with st.form("add_form"):
        front = st.text_input("Word (English)")
        back = st.text_area("Meaning (Korean)")
        etymology = st.text_area("Etymology (optional)")
        synonyms = st.text_input("Synonyms (comma separated)")
        antonyms = st.text_input("Antonyms (comma separated)")
        st.markdown("Examples (up to 3)")
        ex1 = st.text_input("Example 1")
        tr1 = st.text_input("Translation 1")
        ex2 = st.text_input("Example 2")
        tr2 = st.text_input("Translation 2")
        ex3 = st.text_input("Example 3")
        tr3 = st.text_input("Translation 3")
        usage = st.text_input("Usage / Context")
        st.markdown("Pronunciation (optional)")
        pron_us = st.text_input("US pronunciation")
        pron_uk = st.text_input("UK pronunciation")
        context = st.text_area("Context")
        tags = st.text_input("Tags (comma separated)")
        submitted = st.form_submit_button("Add")
        if submitted and front and back:
            syn_list = [s.strip() for s in synonyms.split(",") if s.strip()]
            ant_list = [a.strip() for a in antonyms.split(",") if a.strip()]
            examples = [e for e in [ex1, ex2, ex3] if e.strip()]
            translations = [t for t in [tr1, tr2, tr3] if t.strip()]
            pron = {}
            if pron_us.strip():
                pron['us'] = pron_us.strip()
            if pron_uk.strip():
                pron['uk'] = pron_uk.strip()
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            add_entry(sheet, front.strip(), back.strip(), etymology=etymology.strip(),
                     synonyms=syn_list, antonyms=ant_list, examples=examples,
                     translations=translations, usage=usage.strip(), pronunciation=pron,
                     context=context.strip(), tags=tag_list)
            st.success("Added")
            st.cache_resource.clear()

elif mode == "Browse & Edit":
    st.header("Browse entries")
    q = st.text_input("Search")
    tag = st.text_input("Filter tag")
    rows = list_entries(sheet, query=q or None, tag=tag or None)
    for r in rows:
        cols = st.columns([3, 5, 2, 1])
        with cols[0]:
            st.markdown(f"**{r['front']}**")
            st.write(r["back"])
            if r.get('etymology'):
                st.write(f"Etymology: {r['etymology']}")
        with cols[1]:
            st.write(f"Synonyms: {r.get('synonyms', '')}")
            st.write(f"Antonyms: {r.get('antonyms', '')}")
            try:
                exs = json.loads(r.get('examples', '[]') or '[]')
                trs = json.loads(r.get('translations', '[]') or '[]')
            except Exception:
                exs, trs = [], []
            for i, ex in enumerate(exs):
                tr = trs[i] if i < len(trs) else ""
                st.write(f"Example {i+1}: {ex}")
                if tr:
                    st.write(f" → {tr}")
            st.write(f"Usage / Context: {r.get('context', '')}")
            st.write(f"Tags: {r.get('tags', '')}")
            st.write(f"Due: {r.get('due_at', '')}")
        with cols[2]:
            if st.button(f"Delete {r['id']}"):
                delete_entry(sheet, int(r['id']))
                st.success("Deleted")
                st.cache_resource.clear()
                st.experimental_rerun()

elif mode == "Review (SRS)":
    st.header("Review — Multiple Choice Quiz")
    due_items = list_entries(sheet, due_only=True)
    if not due_items:
        st.info("No items due. Good job!")
    else:
        items_list = list(due_items)
        random.shuffle(items_list)
        
        for r in items_list[:5]:
            st.markdown("---")
            try:
                exs = json.loads(r.get('examples', '[]') or '[]')
            except Exception:
                exs = []
            
            if not exs:
                continue
            
            example_text = random.choice(exs)
            meaning = r['back']
            entry_id = int(r['id'])
            
            st.markdown(f"**Example:** _{example_text}_")
            st.markdown(f"**Question:** What does **{r['front']}** mean?")
            
            wrong_answers = get_random_wrong_answers(sheet, entry_id, 3)
            choices = [meaning] + wrong_answers[:3]
            random.shuffle(choices)
            
            selected = st.radio(f"Choose (ID: {entry_id})", options=choices, key=f"choice_{entry_id}")
            
            if st.button(f"Submit", key=f"submit_{entry_id}"):
                if selected == meaning:
                    st.success("✓ Correct!")
                    update_entry_srs(sheet, entry_id, 5)
                else:
                    st.error(f"✗ Incorrect. Answer: {meaning}")
                    update_entry_srs(sheet, entry_id, 0)
                st.cache_resource.clear()
                st.experimental_rerun()

elif mode == "Stats":
    st.header("Statistics")
    entries = get_all_entries(sheet)
    st.write(f"Total items: {len(entries)}")
    due = sum(1 for e in entries if e.get('due_at', '') <= datetime.utcnow().isoformat())
    st.write(f"Due now: {due}")

st.sidebar.markdown("---")
st.sidebar.write("📊 Cloud-based: Google Sheets")
