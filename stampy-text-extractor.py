#!/usr/bin/python3.12
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
import requests
from requests.auth import HTTPBasicAuth
import argparse
import re
import sys
from typing import List


class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []

    def handle_data(self, d):
        self.text.append(d)

    def get_data(self):
        return ''.join(self.text)


def strip_tags(html_text):
    if html_text is None:
        return ""
    s = MLStripper()
    s.feed(html_text)
    return s.get_data()


@dataclass
class Entry:
    title: str
    pageid: str
    text: str
    answerEditLink: str
    tags: List[str]
    banners: List[str]
    relatedQuestions: List[str]
    status: str
    alternatePhrasings: str
    subtitle: str
    parents: List[str]
    updatedAt: datetime
    order: int


def download_json(local_file: str, refresh: bool, status: str, password: str) -> dict:
    url = 'https://aisafety.info/questions/allQuestions'
    if not password:
        password = os.environ.get('STAMPY_PASSWORD')
    if not password:
        print("Error: Please provide the password or set it in the STAMPY_PASSWORD environment variable.")
        sys.exit(1)
    auth = HTTPBasicAuth('stampy', password)
    params = {'dataType': 'singleFileJson', 'questions': status}

    response = requests.get(url, auth=auth, params=params)
    response.raise_for_status()
    data = response.json()
    with open(local_file, 'w') as file:
        json.dump(data, file)
    return data


def parse_json_data(content: List[dict]) -> List[Entry]:
    entries = []
    for item in content:
        try:
            entry = Entry(
                title=item.get('title', ''),
                pageid=item.get('pageid', ''),
                text=strip_tags(item.get('text', '')),  # Remove HTML tags
                answerEditLink=item.get('answerEditLink', ''),
                tags=item.get('tags', []),
                banners=item.get('banners', []),
                relatedQuestions=item.get('relatedQuestions', []),
                status=item.get('status', ''),
                alternatePhrasings=item.get('alternatePhrasings', ''),
                subtitle=item.get('subtitle', ''),
                parents=item.get('parents', []),
                updatedAt=datetime.fromisoformat(item.get('updatedAt', '').rstrip('Z')) if item.get(
                    'updatedAt') else datetime.min,
                order=item.get('order', 0)
            )
            entries.append(entry)
        except KeyError as e:
            print(f"Skipping entry due to missing key: {e}")
        except ValueError as e:
            print(f"Error parsing entry: {e}")

    return entries


def sanitize_filename(filename):
    # Remove or replace characters that are invalid in filenames
    sanitized = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Limit the length of the filename
    return sanitized[:200]  # Adjust this number as needed


def dump_entries(entries: List[Entry]):
    if os.path.exists('entries'):
        shutil.rmtree('entries')

    # Recreate the 'entries' directory
    os.makedirs('entries')

    excluded_statuses = {"Marked for deletion", "Subsection", "Duplicate"}

    nb_entries = 0

    for entry in entries:
        if entry.status in excluded_statuses:
            continue  # we are not interested in these statuses

        safe_title = sanitize_filename(entry.title)
        filename = f"entries/({entry.status})_{safe_title}.txt"
        try:
            with open(filename, 'w', encoding='utf-8') as file:
                file.write(f"Title: {entry.title}\n\n")
                file.write(entry.text)
            nb_entries += 1
        except OSError as e:
            if e.errno == 36:  # File name too long
                print(f"Error: File name too long for entry '{entry.title[:50]}...'. Skipping this entry.")
            else:
                print(f"Error writing file for entry '{entry.title[:50]}...': {str(e)}")

    print(f"Dumped {nb_entries} entries to the 'entries' directory.")


def search_entries(entries, search_term, case_sensitive=False, whole_word=False):
    results = []
    flags = 0 if case_sensitive else re.IGNORECASE

    if whole_word:
        pattern = r'\b{}\b'.format(re.escape(search_term))
    else:
        pattern = re.escape(search_term)

    for entry in entries:
        title_match = re.search(pattern, entry.title, flags=flags)
        text_match = re.search(pattern, entry.text, flags=flags)

        if title_match or text_match:
            results.append({
                'title': entry.title,
                'status': entry.status,
                'matches': []
            })

            if title_match:
                results[-1]['matches'].append(('title', title_match.start(), title_match.group()))

            for line_num, line in enumerate(entry.text.split('\n'), 1):
                for match in re.finditer(pattern, line, flags=flags):
                    results[-1]['matches'].append(('text', match.group(), line.strip()))

    return results


def main():
    parser = argparse.ArgumentParser(description='Download and parse JSON data.')
    parser.add_argument('--refresh', action='store_true', help='Force refresh the local JSON file')
    parser.add_argument('--dump', action='store_true', help='Dump the text to txt files')
    parser.add_argument('--status', choices=['live', 'inProgress', 'all'], default='all',
                        help='Select which status of questions to include (default: all)')
    parser.add_argument('--password', required=False, help='Password for authentication', default='')

    parser.add_argument('--search', help='Search for a specific term in titles and text')
    parser.add_argument('--case-sensitive', action='store_true', help='Make the search case-sensitive')
    parser.add_argument('--whole-word', action='store_true', help='Search for whole words only')
    args = parser.parse_args()

    local_file = 'stampy_text_html.json'
    if args.refresh or not os.path.exists(local_file):
        json_data = download_json(local_file, args.refresh, args.status, args.password)
    else:
        with open(local_file, 'r') as file:
            json_data = json.load(file)

    entries = parse_json_data(json_data)

    if args.search:
        search_results = search_entries(entries, args.search, args.case_sensitive, args.whole_word)
        if search_results:
            for result in search_results:
                print()
                print(f"Title: {result['title']}")
                print(f"Status: {result['status']}")
                for match in result['matches']:
                    if match[0] == 'title':
                        pass
                    else:
                        print(f"  ...{match[2]}...")
        else:
            print("No matches found.")

    if args.dump:
        dump_entries(entries)


if __name__ == "__main__":
    main()
