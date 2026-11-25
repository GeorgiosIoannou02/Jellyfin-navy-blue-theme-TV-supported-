"""Print library-specific CSS for HD Jellyfin banner artwork. Python 3 only."""
import argparse
import getpass
import json
import sys
from collections import defaultdict
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID


class DirectRequests(HTTPRedirectHandler):
    # The credential is for the supplied server only. Use its final base URL.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def generate(server, key):
    opener = build_opener(DirectRequests())

    def get(path, **query):
        url = server + path + ('?' + urlencode(query) if query else '')
        with opener.open(Request(url, headers={'X-Emby-Token': key}), timeout=45) as response:
            return json.load(response)

    @lru_cache(maxsize=512)
    def artwork(item_id):
        images = get(f'/Items/{item_id}/Images')
        candidates = [image for image in images
                      if image['ImageType'] in ('Thumb', 'Backdrop', 'Primary')
                      and (image.get('Width') or 0) >= 1280 and (image.get('Height') or 0) >= 720
                      and image['Width'] > image['Height']]
        if not candidates:
            return None
        # Prefer a Full HD source, then the native landscape thumbnail.
        best = max(candidates, key=lambda i: (
            i['Width'] >= 1920 and i['Height'] >= 1080,
            {'Thumb': 2, 'Backdrop': 1, 'Primary': 0}[i['ImageType']],
            min(i['Width'], 2560)))
        query = urlencode({'maxWidth': 2560, 'quality': 95, 'tag': best['ImageTag']})
        return f"{server}/Items/{item_id}/Images/{best['ImageType']}/{best.get('ImageIndex', 0)}?{query}"

    groups = defaultdict(list)
    start = 0
    while True:
        result = get('/Items', Recursive='true', IncludeItemTypes='Movie,Episode,Video,MusicVideo',
                     StartIndex=start, Limit=200, SortBy='SortName', EnableImageTypes='Primary,Thumb,Backdrop')
        items = result['Items']
        for item in items:
            item_id = UUID(item['Id']).hex
            image = None
            if item.get('BackdropImageTags') or item.get('ImageTags'):
                image = artwork(item_id)
            if not image and item.get('SeriesId'):
                image = artwork(UUID(item['SeriesId']).hex)
            if image:
                groups[image].append(f'#homeTab .section0 .overflowBackdropCard[data-id="{item_id}"]')
        start += len(items)
        if not items or start >= result['TotalRecordCount']:
            break

    rules = []
    for image, selectors in groups.items():
        rules.append(',\n'.join(selectors) + ' {\n    --jf-featured-art: url("' + image + '");\n}')
    return '\n\n'.join(rules)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server', help='TV-accessible Jellyfin base URL, including any base path')
    args = parser.parse_args()
    url = urlsplit(args.server)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
            or url.query or url.fragment or any(c in url.netloc for c in '"\\')):
        parser.error('Use an HTTP(S) server URL without credentials, query or fragment.')
    server = url._replace(path=quote(url.path.rstrip('/'), safe='/%')).geturl()
    try:
        css = generate(server, getpass.getpass('Jellyfin API key: '))
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        sys.exit(f'Could not generate banner CSS: {error}')
    print(css or '/* No qualifying HD landscape artwork was found. */')
