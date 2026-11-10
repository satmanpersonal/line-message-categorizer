"""Local LINE text export reader. No LINE credentials or network access."""
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re


@dataclass(frozen=True)
class Message:
    # LINE exports contain local wall-clock times, without a UTC offset.
    sent_at: str
    sender: str
    text: str
    raw_identity: str | None = None


def read_export(path):
    raw = Path(path).read_bytes()
    encodings = ("utf-16",) if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "cp932")
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError("Cannot decode this export. Save a UTF-8 or UTF-16 LINE text export.")


def parse_date(line, date_order="MDY"):
    match = re.fullmatch(r"(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})(?:\s*\([^\n]*\)|\s+[^\d\n]+)?", line)
    if match:
        return date(*(int(part) for part in match.groups()))
    match = re.fullmatch(r"(?:[^\d\n,]+,?\s+)?(\d{1,2})/(\d{1,2})/(\d{4})(?:\s*\([^\n]*\))?", line)
    if match:
        first, second, year = (int(part) for part in match.groups())
        month, day = (first, second) if date_order == "MDY" else (second, first)
        return date(year, month, day)
    match = re.fullmatch(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日(?:\s*\([^\n]*\))?", line)
    if match:
        return date(*(int(part) for part in match.groups()))
    for fmt in ("%A, %B %d, %Y", "%B %d, %Y", "%A, %d %B %Y", "%d %B %Y"):
        try:
            return datetime.strptime(line, fmt).date()
        except ValueError:
            pass
    return None


def parse_export(text, fallback_chat, date_order="MDY", sender_names=()):
    """Read dated, tab-separated LINE exports; retain multiline message bodies."""
    if date_order not in ("MDY", "DMY"):
        raise ValueError("date_order must be MDY or DMY")
    chat = fallback_chat
    current_date = None
    pending = None
    messages = []

    def finish():
        if pending:
            stamp, sender, parts, raw_parts = pending
            while len(parts) > 1 and parts[-1] == "":
                parts.pop()
            raw_identity = "space:" + "\n".join(raw_parts).rstrip("\n") if raw_parts is not None else None
            messages.append(Message(stamp, sender, "\n".join(parts), raw_identity))

    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter="\t", strict=True)
    try:
        for fields in reader:
            number = reader.line_num
            line = "\t".join(fields)
            if line.startswith("[LINE] ") and current_date is None:
                title = line[len("[LINE] "):].strip()
                for prefix in ("Chat history with ", "Chat history of "):
                    if title.startswith(prefix):
                        chat = title[len(prefix):].strip()
                        break
                else:
                    for suffix in ("とのトーク履歴", "のトーク履歴"):
                        if title.endswith(suffix):
                            chat = title[:-len(suffix)].strip()
                            break
                continue
            day = parse_date(line.strip(), date_order) if len(fields) <= 1 else None
            if day:
                finish()
                pending = None
                current_date = day
                continue
            clock = fields[0] if fields else ""
            space_record = re.fullmatch(r"(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?) (.+)", line) if len(fields) == 1 else None
            raw_parts = None
            if space_record:
                clock, remainder = space_record.groups()
                known_names = sorted(set(sender_names) | {chat}, key=len, reverse=True)
                sender = next((name for name in known_names if remainder.startswith(name + " ")), "")
                body = remainder[len(sender)+1:] if sender else remainder
                if not sender and remainder in ("メッセージの送信を取り消しました", "You unsent a message."):
                    sender = "[System]"
                fields = [clock, sender, body]
                raw_parts = [remainder]
            if len(fields) >= 2 and re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?", clock):
                if current_date is None:
                    raise ValueError(f"Message at line {number} has no recognized date header")
                parsed_clock = None
                for fmt in ("%H:%M", "%H:%M:%S", "%I:%M%p", "%I:%M %p"):
                    try:
                        parsed_clock = datetime.strptime(clock.upper(), fmt).time()
                        break
                    except ValueError:
                        pass
                if parsed_clock is None:
                    raise ValueError(f"Invalid message time at line {number}: {clock}")
                finish()
                stamp = datetime.combine(current_date, parsed_clock).isoformat(timespec="seconds")
                sender, body = (fields[1].strip(), "\t".join(fields[2:])) if len(fields) >= 3 else ("[System]", fields[1])
                pending = (stamp, sender, [body], raw_parts)
            elif pending is not None:
                pending[2].append(line)
                if pending[3] is not None:
                    pending[3].append(line)
            elif current_date is not None and line.strip():
                raise ValueError(f"Unsupported LINE export line {number}. Expected time<TAB>sender<TAB>message.")
    except csv.Error as error:
        raise ValueError(f"Invalid quoted message near line {reader.line_num}: {error}") from error
    finish()
    if not messages:
        raise ValueError("No messages found. Select a LINE Save chat .txt export with date headers and tab-separated messages.")
    if not chat.strip():
        raise ValueError("The export has no chat name")
    return chat, messages


def import_file(store, path, config):
    path = Path(path)
    fallback = re.sub(r"^\[LINE\]\s*", "", path.stem)
    chat, messages = parse_export(read_export(path), fallback, config.get("date_order", "MDY"), config.get("sender_names", []))
    added = store.import_messages(chat, messages, config["categories"], path,
                                  config.get("chat_categories", {}))
    return chat, len(messages), added, sum(not message.sender for message in messages)


