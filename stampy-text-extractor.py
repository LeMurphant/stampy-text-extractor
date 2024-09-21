#!/usr/bin/python3.10
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import argparse
import re
import sys
from bs4 import BeautifulSoup
from pathvalidate import sanitize_filename
from typing import List, Union


def strip_tags(html_text):
    if html_text is None:
        return ""
    soup = BeautifulSoup(html_text, 'html.parser')
    return soup.get_text()


@dataclass(frozen=True)
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
    URLs: str


def download_json(local_file: str, status: str, password: str) -> dict:
    """Download the JSON file from aisafety.info"""
    url = 'https://aisafety.info/questions/allQuestions'
    if not password:
        password = os.environ.get('STAMPY_PASSWORD')
    if not password:
        print("Error: Please provide the password or set it in the STAMPY_PASSWORD environment variable.")
        sys.exit(1)
    auth = HTTPBasicAuth('stampy', password)  # the authentication is known to be weak
    params = {'dataType': 'singleFileJson', 'questions': status}

    response = requests.get(url, auth=auth, params=params)
    response.raise_for_status()
    data = response.json()
    with open(local_file, 'w') as file:
        json.dump(data, file)
    return data


def parse_json_data(content: List[dict]) -> List[Entry]:
    """
    Convert the JSON data into a list of entries (articles).
    Only articles with relevant statuses are kept.
    """
    excluded_statuses = {"Marked for deletion", "Subsection", "Duplicate"}

    entries = []
    for item in content:
        try:
            rawtext = item.get('text', '')
            urls = extract_urls(rawtext)
            entry = Entry(
                title=item.get('title', ''),
                pageid=item.get('pageid', ''),
                text=strip_tags(rawtext),
                answerEditLink=item.get('answerEditLink', ''),
                tags=item.get('tags', []),
                banners=item.get('banners', []),
                relatedQuestions=item.get('relatedQuestions', []),
                status=item.get('status', ''),
                alternatePhrasings=item.get('alternatePhrasings', ''),
                subtitle=item.get('subtitle', ''),
                parents=item.get('parents', []),
                updatedAt=parse_datetime(item.get('updatedAt', '')),
                order=item.get('order', 0),
                URLs=urls
            )
            if entry.status not in excluded_statuses:
                entries.append(entry)

        except ValueError as e:
            print(f"Error parsing entry: {e}")

    return entries


def extract_urls(text: Union[str, None]) -> List[str]:
    if text is None:
        return []

    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception as e:
            print(f"Error converting text to string: {e}")
            return []

    # http URLs
    url_pattern = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')
    # internal URLs
    state_url_pattern = re.compile(r'\/\?state=[A-Za-z0-9]{4}&amp;question=[^"]+')

    standard_urls = url_pattern.findall(text)
    state_urls = state_url_pattern.findall(text)
    return standard_urls + state_urls


def parse_datetime(date_string: str) -> datetime:
    if not date_string:
        return datetime.min
    return datetime.fromisoformat(date_string.rstrip('Z'))


def dump_entries(entries: List[Entry]):
    """Extract entries into individual text files"""

    # remove all files in the "entries" folder
    if os.path.exists('entries'):
        shutil.rmtree('entries')
    os.makedirs('entries')

    nb_entries = 0

    for entry in entries:
        safe_title = sanitize_filename(entry.title, platform='auto')
        filename = f"entries/({entry.status})_{safe_title}.txt"
        try:
            with open(filename, 'w', encoding='utf-8') as file:
                file.write(f"Title: {entry.title}\n\n")
                file.write("URLs:\n")
                for url in entry.URLs:
                    file.write(f"- {url}\n")
                file.write("\n")
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
        url_matches = [re.search(pattern, url, flags=flags) for url in entry.URLs]

        if title_match or text_match or any(url_matches):
            result = {
                'title': entry.title,
                'status': entry.status,
                'matches': []
            }

            if title_match:
                result['matches'].append(('title', title_match.start(), title_match.group()))

            for line_num, line in enumerate(entry.text.split('\n'), 1):
                for match in re.finditer(pattern, line, flags=flags):
                    result['matches'].append(('text', match.group(), line.strip()))

            for url, url_match in zip(entry.URLs, url_matches):
                if url_match:
                    result['matches'].append(('url', url_match.group(), url))

            results.append(result)

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
        json_data = download_json(local_file, args.status, args.password)
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
