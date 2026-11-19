#!/usr/bin/env python3
"""mailcli - CLI pour lire les mails (Gmail via IMAP, mot de passe d'application).

Commandes:
  setup            Configure le compte (email + mot de passe d'application)
  whoami           Affiche le compte configuré
  folders          Liste les dossiers
  list [DOSSIER]   Liste les mails récents
  read UID         Affiche le contenu d'un mail
  search [TEXTE]   Recherche des mails (IMAP ou --raw Gmail)
  unread-count     Compte les mails non lus
  mark-read UID    Marque un mail comme lu
  mark-unread UID  Marque un mail comme non lu
  delete UID       Supprime un mail (le déplace dans la corbeille Gmail)
  attachments UID  Liste les pièces jointes d'un mail
  download UID     Télécharge les pièces jointes d'un mail

Passez --json (en fin de commande) pour un output machine-readable.
"""
import argparse
import email
import getpass
import html
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "mailcli"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
}

# ---------- rich optionnel ----------
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    RICH = True
    console = Console()
except Exception:
    RICH = False
    console = None


def out(msg=""):
    if RICH:
        console.print(msg)
    else:
        print(msg)


def err(msg):
    if RICH:
        console.print(f"[red]{msg}[/red]")
    else:
        print(msg, file=sys.stderr)


# ---------- config ----------
def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)


def get_creds(profile="default"):
    cfg = load_config()
    email_addr = os.environ.get("MAILCLI_EMAIL") or cfg.get("email")
    password = os.environ.get("MAILCLI_PASSWORD") or cfg.get("password")
    host = os.environ.get("MAILCLI_IMAP_HOST") or cfg.get("imap_host", DEFAULTS["imap_host"])
    port = int(os.environ.get("MAILCLI_IMAP_PORT") or cfg.get("imap_port", DEFAULTS["imap_port"]))
    if not email_addr or not password:
        err("Aucun compte configuré. Lance: mailcli setup")
        sys.exit(1)
    return email_addr, password, host, port


def connect(profile="default"):
    email_addr, password, host, port = get_creds(profile)
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(email_addr, password)
    return conn, email_addr


# ---------- décodage ----------
def decode_str(s):
    if s is None:
        return ""
    try:
        parts = decode_header(s)
    except Exception:
        return str(s)
    out_parts = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out_parts.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out_parts.append(str(part))
    return "".join(out_parts)


def html_to_text(h):
    class P(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.skip = 0
        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "head"):
                self.skip += 1
            if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
                self.parts.append("\n")
        def handle_startendtag(self, tag, attrs):
            if tag == "br":
                self.parts.append("\n")
        def handle_endtag(self, tag):
            if tag in ("script", "style", "head"):
                self.skip = max(0, self.skip - 1)
            if tag in ("p", "div", "li", "tr", "h1", "h2", "h3"):
                self.parts.append("\n")
        def handle_data(self, data):
            if self.skip:
                return
            self.parts.append(data)
        def get_text(self):
            t = "".join(self.parts)
            t = re.sub(r"[ \t]+\n", "\n", t)
            t = re.sub(r"\n{3,}", "\n\n", t)
            return t.strip()
    p = P()
    try:
        p.feed(h)
    except Exception:
        pass
    return p.get_text()


def parse_message(msg_bytes):
    msg = email.message_from_bytes(msg_bytes)
    subject = decode_str(msg.get("Subject"))
    from_ = decode_str(msg.get("From"))
    to = decode_str(msg.get("To"))
    cc = decode_str(msg.get("Cc"))
    date = msg.get("Date")
    try:
        dt = parsedate_to_datetime(date) if date else None
    except Exception:
        dt = None
    text = None
    html_body = None
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            fname = part.get_filename()
            if fname:
                payload = part.get_payload(decode=True)
                attachments.append({
                    "filename": decode_str(fname),
                    "content_type": ctype,
                    "size": len(payload) if payload is not None else 0,
                    "payload": payload,
                })
                continue
            if "attachment" in disp:
                # pièce jointe sans nom de fichier
                payload = part.get_payload(decode=True)
                attachments.append({
                    "filename": f"attachment_{len(attachments)+1}.bin",
                    "content_type": ctype,
                    "size": len(payload) if payload is not None else 0,
                    "payload": payload,
                })
                continue
            if ctype == "text/plain" and text is None:
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
            elif ctype == "text/html" and html_body is None:
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    html_body = payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            if msg.get_content_type() == "text/html":
                html_body = payload.decode(charset, errors="replace")
            else:
                text = payload.decode(charset, errors="replace")
    if text is None and html_body:
        text = html_to_text(html_body)
    return {
        "subject": subject,
        "from": from_,
        "to": to,
        "cc": cc,
        "date": date,
        "dt": dt,
        "text": text or "",
        "html": html_body,
        "attachments": attachments,
        "message_id": msg.get("Message-ID"),
    }


# ---------- fetch helpers ----------
def fetch_headers(conn, uids):
    if not uids:
        return []
    uid_str = b",".join(uids)
    typ, data = conn.uid("FETCH", uid_str, "(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER])")
    if typ != "OK":
        return []
    msgs = []
    for item in data:
        if item is None:
            continue
        if isinstance(item, tuple):
            meta, body = item
            msgs.append((meta, body))
    results = []
    for meta, body in msgs:
        meta_str = meta.decode("utf-8", errors="replace") if isinstance(meta, (bytes, bytearray)) else str(meta)
        uid_m = re.search(r"UID (\d+)", meta_str)
        uid = uid_m.group(1) if uid_m else None
        flags_m = re.search(r"FLAGS \(([^)]*)\)", meta_str)
        flags = flags_m.group(1) if flags_m else ""
        size_m = re.search(r"RFC822\.SIZE (\d+)", meta_str)
        size = int(size_m.group(1)) if size_m else 0
        try:
            msg = email.message_from_bytes(body)
        except Exception:
            msg = None
        subject = decode_str(msg.get("Subject")) if msg else ""
        from_ = decode_str(msg.get("From")) if msg else ""
        date = msg.get("Date") if msg else ""
        try:
            dt = parsedate_to_datetime(date) if date else None
        except Exception:
            dt = None
        results.append({
            "uid": uid,
            "flags": flags,
            "size": size,
            "subject": subject,
            "from": from_,
            "date": date,
            "dt": dt,
            "unread": "\\Seen" not in flags,
        })
    # preserve uid order as requested
    order = {u.decode() if isinstance(u, (bytes, bytearray)) else str(u): i for i, u in enumerate(uids)}
    results.sort(key=lambda r: order.get(r["uid"], 9999))
    return results


def emit_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def human_size(n):
    for unit in ("o", "Ko", "Mo"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "o" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}Go"


import base64 as _b64


def decode_imap_utf7(s):
    """Décode un nom de mailbox IMAP (modified UTF-7) en UTF-8."""
    if s is None:
        return s
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "&":
            j = s.find("-", i)
            if j == -1:
                out.append(s[i:])
                break
            if j == i + 1:
                out.append("&")
            else:
                b64 = s[i + 1:j].replace(",", "/")
                pad = (-len(b64)) % 4
                try:
                    out.append(_b64.b64decode(b64 + "=" * pad).decode("utf-16-be"))
                except Exception:
                    out.append(s[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def encode_imap_utf7(s):
    """Encode un nom de mailbox en modified UTF-7 si nécessaire."""
    if s is None:
        return s
    if all(ord(c) < 128 for c in s):
        return s
    out = []
    buf = []

    def flush():
        nonlocal buf
        if buf:
            text = "".join(buf)
            b64 = _b64.b64encode(text.encode("utf-16-be")).decode("ascii").rstrip("=")
            b64 = b64.replace("/", ",")
            out.append("&" + b64 + "-")
            buf = []

    for c in s:
        if 0x20 <= ord(c) <= 0x7e and c != "&":
            flush()
            out.append(c)
        elif c == "&":
            flush()
            out.append("&-")
        else:
            buf.append(c)
    flush()
    return "".join(out)


def imap_folder(name):
    return encode_imap_utf7(name) if name else name


def quote_mailbox(name):
    if name is None:
        return name
    if isinstance(name, (bytes, bytearray)):
        name = name.decode("utf-8", errors="replace")
    if name.startswith('"') and name.endswith('"'):
        return name
    if " " in name or any(c in name for c in '()[]{}"\\'):
        return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return name


def imap_date(s):
    """Convertit YYYY-MM-DD en date IMAP DD-Mon-YYYY."""
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return d.strftime("%d-%b-%Y")
    except ValueError:
        # déjà au format IMAP ?
        return s


# ---------- commandes ----------
def cmd_setup(args):
    out("=== Configuration mailcli ===")
    email_addr = input("Email Gmail: ").strip()
    print("Mot de passe d'application (16 caractères, espaces acceptés):")
    password = getpass.getpass("App password: ").strip().replace(" ", "")
    host = input(f"Serveur IMAP [{DEFAULTS['imap_host']}]: ").strip() or DEFAULTS["imap_host"]
    port_s = input(f"Port [{DEFAULTS['imap_port']}]: ").strip() or str(DEFAULTS["imap_port"])
    try:
        conn = imaplib.IMAP4_SSL(host, int(port_s))
        conn.login(email_addr, password)
        conn.logout()
    except Exception as e:
        err(f"Échec de connexion: {e}")
        sys.exit(1)
    save_config({
        "email": email_addr,
        "password": password,
        "imap_host": host,
        "imap_port": int(port_s),
    })
    out(f"[green]Compte enregistré.[/green] Config: {CONFIG_FILE}")


def cmd_whoami(args):
    cfg = load_config()
    if not cfg.get("email"):
        err("Aucun compte configuré. Lance: mailcli setup")
        return
    out(f"Email : {cfg.get('email')}")
    out(f"IMAP  : {cfg.get('imap_host')}:{cfg.get('imap_port')}")
    out(f"Config: {CONFIG_FILE}")


def cmd_folders(args):
    conn, email_addr = connect()
    typ, data = conn.list()
    if typ != "OK":
        err("Impossible de lister les dossiers")
        conn.logout()
        return
    names = []
    for item in data:
        if not item:
            continue
        line = item.decode("utf-8", errors="replace") if isinstance(item, (bytes, bytearray)) else str(item)
        # format: (\HasNoChildren) "/" "INBOX"
        m = re.search(r'"([^"]+)"\s*$', line)
        if m:
            names.append(decode_imap_utf7(m.group(1)))
        else:
            parts = line.split()
            if parts:
                names.append(decode_imap_utf7(parts[-1].strip('"')))
    if getattr(args, "json", False):
        emit_json(names)
        conn.logout()
        return
    if RICH:
        t = Table(title="Dossiers")
        t.add_column("#", style="dim")
        t.add_column("Nom")
        for i, n in enumerate(names, 1):
            t.add_row(str(i), n)
        console.print(t)
    else:
        for n in names:
            print(n)
    conn.logout()


def cmd_list(args):
    conn, email_addr = connect()
    folder = imap_folder(args.folder or "INBOX")
    try:
        conn.select(quote_mailbox(folder), readonly=True)
    except Exception as e:
        err(f"Dossier introuvable: {decode_imap_utf7(folder)} ({e})")
        conn.logout()
        return
    criteria = "UNSEEN" if args.unread else "ALL"
    typ, data = conn.uid("SEARCH", None, criteria)
    if typ != "OK":
        err("Échec de la recherche")
        conn.logout()
        return
    uids = data[0].split() if data and data[0] else []
    if not uids:
        if getattr(args, "json", False):
            emit_json([])
        else:
            out("Aucun mail.")
        conn.logout()
        return
    limit = args.limit or 20
    selected = uids[-limit:]
    selected = list(reversed(selected))
    rows = fetch_headers(conn, selected)
    if getattr(args, "json", False):
        emit_json([{"uid": r["uid"], "date": r["date"], "from": r["from"], "subject": r["subject"], "size": r["size"], "unread": r["unread"]} for r in rows])
        conn.logout()
        return
    if RICH:
        t = Table(title=f"{decode_imap_utf7(folder)} — {len(rows)} mail(s)")
        t.add_column("UID", style="dim", width=8)
        t.add_column("Date", width=16)
        t.add_column("De", width=28, overflow="ellipsis")
        t.add_column("Sujet", overflow="ellipsis")
        t.add_column("Taille", width=7)
        t.add_column("", width=3)
        for r in rows:
            date_str = ""
            if r["dt"]:
                date_str = r["dt"].strftime("%d/%m %H:%M")
            elif r["date"]:
                date_str = r["date"][:16]
            flag = "✉" if r["unread"] else " "
            t.add_row(r["uid"] or "", date_str, r["from"], r["subject"], human_size(r["size"]), flag)
        console.print(t)
        out("[dim]✉ = non lu. Utilise 'mailcli read UID' pour lire.[/dim]")
    else:
        for r in rows:
            flag = "*" if r["unread"] else " "
            print(f"{flag} {r['uid']}  {r['date'][:20]:20}  {r['from'][:30]:30}  {r['subject']}")
    conn.logout()


def cmd_read(args):
    conn, email_addr = connect()
    folder = imap_folder(args.folder or "INBOX")
    conn.select(quote_mailbox(folder), readonly=True)
    uid = args.uid.encode() if isinstance(args.uid, str) else args.uid
    typ, data = conn.uid("FETCH", uid, "(RFC822)")
    if typ != "OK" or not data or not data[0]:
        err(f"Mail introuvable: {args.uid}")
        conn.logout()
        return
    raw = data[0][1] if isinstance(data[0], tuple) else data[0]
    parsed = parse_message(raw)
    if getattr(args, "json", False):
        emit_json({"uid": args.uid, "subject": parsed["subject"], "from": parsed["from"], "to": parsed["to"], "cc": parsed["cc"], "date": parsed["date"], "attachments": [{"filename": a["filename"], "content_type": a["content_type"], "size": a["size"]} for a in parsed["attachments"]], "text": parsed["text"]})
        conn.logout()
        if args.mark_read:
            conn2, _ = connect()
            conn2.select(quote_mailbox(folder))
            conn2.uid("STORE", uid, "+FLAGS", "\\Seen")
            conn2.logout()
        return
    # affichage
    if RICH:
        console.print(Panel.fit(f"[bold]{parsed['subject']}[/bold]", title="Sujet"))
        console.print(f"[cyan]De      :[/cyan] {parsed['from']}")
        console.print(f"[cyan]À      :[/cyan] {parsed['to']}")
        if parsed["cc"]:
            console.print(f"[cyan]Cc     :[/cyan] {parsed['cc']}")
        console.print(f"[cyan]Date   :[/cyan] {parsed['date']}")
        if parsed["attachments"]:
            atts = ", ".join(f"{a['filename']} ({human_size(a['size'])})" for a in parsed["attachments"])
            console.print(f"[cyan]Pièces :[/cyan] {atts}")
        console.print()
        console.print(parsed["text"])
    else:
        print(f"Sujet: {parsed['subject']}")
        print(f"De: {parsed['from']}")
        print(f"À: {parsed['to']}")
        print(f"Date: {parsed['date']}")
        if parsed["attachments"]:
            atts = ", ".join(f"{a['filename']} ({human_size(a['size'])})" for a in parsed["attachments"])
            print(f"Pièces: {atts}")
        print("-" * 60)
        print(parsed["text"])
    conn.logout()
    if args.mark_read:
        # re-open rw and mark
        conn2, _ = connect()
        conn2.select(folder)
        conn2.uid("STORE", uid, "+FLAGS", "\\Seen")
        conn2.logout()


def cmd_search(args):
    conn, email_addr = connect()
    folder = imap_folder(args.folder or "INBOX")
    conn.select(quote_mailbox(folder), readonly=True)
    if getattr(args, "raw", None):
        # Requête Gmail brute via X-GM-RAW
        typ, data = conn.uid("SEARCH", None, "X-GM-RAW", f'"{args.raw}"')
    else:
        parts = []
        if args.unread:
            parts.append("UNSEEN")
        if args.from_:
            parts.append(f'FROM "{args.from_}"')
        if args.subject:
            parts.append(f'SUBJECT "{args.subject}"')
        if args.since:
            parts.append(f"SINCE {imap_date(args.since)}")
        if args.before:
            parts.append(f"BEFORE {imap_date(args.before)}")
        if args.text:
            parts.append(f'TEXT "{args.text}"')
        if args.query:
            parts.append(f'TEXT "{args.query}"')
        if not parts:
            parts.append("ALL")
        crit = " ".join(parts)
        typ, data = conn.uid("SEARCH", None, crit)
    if typ != "OK":
        err(f"Échec recherche: {data}")
        conn.logout()
        return
    uids = data[0].split() if data and data[0] else []
    if not uids:
        if getattr(args, "json", False):
            emit_json([])
        else:
            out("Aucun résultat.")
        conn.logout()
        return
    limit = args.limit or 30
    selected = uids[-limit:]
    selected = list(reversed(selected))
    rows = fetch_headers(conn, selected)
    if getattr(args, "json", False):
        emit_json([{"uid": r["uid"], "date": r["date"], "from": r["from"], "subject": r["subject"], "size": r["size"], "unread": r["unread"]} for r in rows])
        conn.logout()
        return
    if RICH:
        t = Table(title=f"Résultats: {len(rows)} mail(s)")
        t.add_column("UID", style="dim", width=8)
        t.add_column("Date", width=16)
        t.add_column("De", width=28, overflow="ellipsis")
        t.add_column("Sujet", overflow="ellipsis")
        t.add_column("", width=3)
        for r in rows:
            date_str = r["dt"].strftime("%d/%m %H:%M") if r["dt"] else (r["date"] or "")[:16]
            t.add_row(r["uid"] or "", date_str, r["from"], r["subject"], "✉" if r["unread"] else " ")
        console.print(t)
    else:
        for r in rows:
            print(f"{r['uid']}  {r['date'][:20]:20}  {r['from'][:30]:30}  {r['subject']}")
    conn.logout()


def cmd_mark(args, flag, add):
    conn, _ = connect()
    folder = imap_folder(args.folder or "INBOX")
    conn.select(quote_mailbox(folder))
    uid = args.uid.encode() if isinstance(args.uid, str) else args.uid
    op = "+FLAGS" if add else "-FLAGS"
    conn.uid("STORE", uid, op, flag)
    conn.logout()
    out(f"OK: {args.uid}")


def cmd_delete(args):
    conn, _ = connect()
    folder = imap_folder(args.folder or "INBOX")
    conn.select(quote_mailbox(folder))
    uid = args.uid.encode() if isinstance(args.uid, str) else args.uid
    # Gmail: move to Trash via COPY + STORE \Deleted + EXPUNGE, or use X-GM-LABELS
    # Simpler: STORE \Deleted then EXPUNGE (Gmail moves to trash? Actually \Deleted+EXPUNGE permanently deletes in Gmail unless in All Mail).
    # Use Gmail extension: copy to [Gmail]/Corbeille
    trash = None
    typ, data = conn.list()
    for item in data:
        line = item.decode("utf-8", errors="replace") if isinstance(item, (bytes, bytearray)) else str(item)
        if "Trash" in line or "Corbeille" in line or "Bin" in line:
            m = re.search(r'"([^"]+)"\s*$', line)
            if m:
                trash = m.group(1)
                break
    if trash:
        conn.uid("COPY", uid, quote_mailbox(trash))
    conn.uid("STORE", uid, "+FLAGS", "\\Deleted")
    conn.expunge()
    conn.logout()
    out(f"Supprimé: {args.uid}" + (f" (copié dans {trash})" if trash else ""))


def get_attachments(args):
    """Récupère la liste des pièces jointes d'un mail."""
    conn, email_addr = connect()
    folder = imap_folder(args.folder or "INBOX")
    conn.select(quote_mailbox(folder), readonly=True)
    uid = args.uid.encode() if isinstance(args.uid, str) else args.uid
    typ, data = conn.uid("FETCH", uid, "(RFC822)")
    if typ != "OK" or not data or not data[0]:
        conn.logout()
        return None, f"Mail introuvable: {args.uid}"
    raw = data[0][1] if isinstance(data[0], tuple) else data[0]
    parsed = parse_message(raw)
    conn.logout()
    return parsed.get("attachments", []), None


def sanitize_filename(name):
    name = os.path.basename(name or "attachment.bin")
    # remplace les caractères dangereux
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    name = name.strip(" .")
    if not name:
        name = "attachment.bin"
    return name


def unique_path(directory, filename):
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base} ({i}){ext}")
        i += 1
    return candidate


def cmd_attachments(args):
    atts, err_msg = get_attachments(args)
    if err_msg:
        err(err_msg)
        return
    if not atts:
        if getattr(args, "json", False):
            emit_json([])
        else:
            out("Aucune pièce jointe.")
        return
    if getattr(args, "json", False):
        emit_json([{"index": i, "filename": a["filename"], "content_type": a["content_type"], "size": a["size"]} for i, a in enumerate(atts, 1)])
        return
    if RICH:
        t = Table(title=f"Pièces jointes — UID {args.uid}")
        t.add_column("#", style="dim", width=4)
        t.add_column("Nom", overflow="ellipsis")
        t.add_column("Type", width=24)
        t.add_column("Taille", width=10)
        for i, a in enumerate(atts, 1):
            t.add_row(str(i), a["filename"], a["content_type"], human_size(a["size"]))
        console.print(t)
    else:
        for i, a in enumerate(atts, 1):
            print(f"{i}. {a['filename']}  {a['content_type']}  {human_size(a['size'])}")


def cmd_download(args):
    atts, err_msg = get_attachments(args)
    if err_msg:
        err(err_msg)
        return
    if not atts:
        if getattr(args, "json", False):
            emit_json([])
        else:
            out("Aucune pièce jointe à télécharger.")
        return
    out_dir = args.output or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    # sélection
    if args.index is not None:
        if args.index < 1 or args.index > len(atts):
            err(f"Index invalide (1..{len(atts)})")
            return
        selected = [atts[args.index - 1]]
    else:
        selected = atts
    saved = []
    for a in selected:
        fname = sanitize_filename(a["filename"])
        dest = unique_path(out_dir, fname)
        data = a.get("payload")
        if data is None:
            err(f"Contenu vide: {a['filename']}")
            continue
        with open(dest, "wb") as f:
            f.write(data)
        saved.append(dest)
        out(f"[green]Téléchargé:[/green] {dest}  ({human_size(len(data))})")
    if not saved:
        err("Aucun fichier téléchargé.")
        return
    if getattr(args, "json", False):
        emit_json([{"path": p, "size": os.path.getsize(p)} for p in saved])


def cmd_unread_count(args):
    conn, email_addr = connect()
    folder = imap_folder(args.folder or "INBOX")
    try:
        conn.select(quote_mailbox(folder), readonly=True)
    except Exception as e:
        err(f"Dossier introuvable: {decode_imap_utf7(folder)} ({e})")
        conn.logout()
        return
    typ, data = conn.uid("SEARCH", None, "UNSEEN")
    conn.logout()
    count = len(data[0].split()) if typ == "OK" and data and data[0] else 0
    if getattr(args, "json", False):
        emit_json({"folder": decode_imap_utf7(folder), "unread": count})
    else:
        print(count)


def main():
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--json", action="store_true", help="Sortie JSON (machine-readable)")
    parser = argparse.ArgumentParser(prog="mailcli", description="Lire ses mails Gmail via IMAP", parents=[parent_parser])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="Configurer le compte", parents=[parent_parser])
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("whoami", help="Afficher le compte configuré", parents=[parent_parser])
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser("folders", help="Lister les dossiers", parents=[parent_parser])
    p.set_defaults(func=cmd_folders)

    p = sub.add_parser("list", help="Lister les mails", parents=[parent_parser])
    p.add_argument("folder", nargs="?", default="INBOX", help="Dossier (défaut INBOX)")
    p.add_argument("-n", "--limit", type=int, default=20, help="Nombre de mails")
    p.add_argument("-u", "--unread", action="store_true", help="Non lus seulement")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("read", help="Lire un mail par UID", parents=[parent_parser])
    p.add_argument("uid", help="UID du mail")
    p.add_argument("-f", "--folder", default="INBOX")
    p.add_argument("--mark-read", action="store_true", help="Marquer comme lu")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("search", help="Rechercher des mails", parents=[parent_parser])
    p.add_argument("query", nargs="?", help="Texte à rechercher (dans le corps)")
    p.add_argument("--from", dest="from_", help="Expéditeur")
    p.add_argument("--subject", help="Sujet contient")
    p.add_argument("--text", help="Texte dans le corps")
    p.add_argument("--since", help="Depuis (YYYY-MM-DD)")
    p.add_argument("--before", help="Avant (YYYY-MM-DD)")
    p.add_argument("--raw", help="Requête Gmail brute (X-GM-RAW), ex. 'has:attachment larger:5M'")
    p.add_argument("-u", "--unread", action="store_true", help="Non lus seulement")
    p.add_argument("-f", "--folder", default="INBOX")
    p.add_argument("-n", "--limit", type=int, default=30)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("mark-read", help="Marquer comme lu", parents=[parent_parser])
    p.add_argument("uid")
    p.add_argument("-f", "--folder", default="INBOX")
    p.set_defaults(func=lambda a: cmd_mark(a, "\\Seen", True))

    p = sub.add_parser("mark-unread", help="Marquer comme non lu", parents=[parent_parser])
    p.add_argument("uid")
    p.add_argument("-f", "--folder", default="INBOX")
    p.set_defaults(func=lambda a: cmd_mark(a, "\\Seen", False))

    p = sub.add_parser("delete", help="Supprimer un mail", parents=[parent_parser])
    p.add_argument("uid")
    p.add_argument("-f", "--folder", default="INBOX")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("attachments", help="Lister les pièces jointes d'un mail", parents=[parent_parser])
    p.add_argument("uid")
    p.add_argument("-f", "--folder", default="INBOX")
    p.set_defaults(func=cmd_attachments)

    p = sub.add_parser("download", help="Télécharger les pièces jointes d'un mail", parents=[parent_parser])
    p.add_argument("uid")
    p.add_argument("-f", "--folder", default="INBOX")
    p.add_argument("-o", "--output", help="Dossier de destination (défaut: répertoire courant)")
    p.add_argument("-i", "--index", type=int, help="Télécharger seulement la pièce jointe N (1-based)")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("unread-count", help="Nombre de mails non lus", parents=[parent_parser])
    p.add_argument("folder", nargs="?", default="INBOX", help="Dossier (défaut INBOX)")
    p.set_defaults(func=cmd_unread_count)

    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except Exception as e:
        err(f"Erreur: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()