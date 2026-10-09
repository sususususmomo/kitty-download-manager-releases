"""Real Gecko DOM regression fixtures. Offline TikTok cards, no user session.

Requires Selenium and KITTY_FIREFOX_BINARY/KITTY_GECKODRIVER; accepts
KITTY_TEST_EXTENSION for a before/after comparison against the old resolver.
"""
import json
import os
from pathlib import Path
import sys
import urllib.parse
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

ROOT = Path(__file__).resolve().parents[1]
EXT = Path(os.environ.get('KITTY_TEST_EXTENSION', ROOT / 'extension'))
A = '7660560870455840021'
B = '7660560870455840022'
C = '7660560870455840023'
FEED = 'https://www.tiktok.com/foryou'
url = lambda video_id: 'https://www.tiktok.com/@kitty/video/' + video_id
report = {'checks': [], 'failures': [], 'fixture': 'offline TikTok DOM in real Firefox'}
options = Options()
options.add_argument('-headless')
options.binary_location = os.environ['KITTY_FIREFOX_BINARY']
driver = webdriver.Firefox(options=options, service=Service(os.environ['KITTY_GECKODRIVER']))
driver.set_window_size(1280, 900)

def card(video_id, top=20, *, wrong_link=None, hidden=False, modern=False):
    selector = 'data-e2e="feed-item"' if modern else f'data-cinema-mode-snap-row="{video_id}"'
    return f'''<section {selector} style="position:absolute;top:{top}px;width:600px;height:600px;visibility:{'hidden' if hidden else 'visible'}">
      <div id="xgwrapper-0-{video_id}" class="xgplayer-container">
      <video src="blob:https://www.tiktok.com/fixture" style="width:500px;height:480px"></video></div>
      <a href="/@kitty">@kitty</a>
      {f'<a href="{url(wrong_link)}">comment video</a>' if wrong_link else ''}
    </section>'''

def load(page, html):
    driver.get('data:text/html;charset=utf-8,' + urllib.parse.quote('<base href="'+page+'">'+html))
    source = '(function(location){' + (EXT / 'media-resolver.js').read_text() + '})(new URL('+json.dumps(page)+'));\n' + (EXT / 'media-dom.js').read_text()
    driver.execute_script('const script=document.createElement("script");script.textContent=arguments[0];document.documentElement.appendChild(script);', source)

def resolved():
    return driver.execute_script('return KittyMediaResolver.resolveMediaUrlForPage(true)')

def snapshots():
    return driver.execute_script('return KittyMediaDOM.scan()')

def check(name, test):
    try:
        test()
        report['checks'].append(name)
        print('PASS', name)
    except Exception as error:
        report['failures'].append({'name': name, 'error': str(error)})
        print('FAIL', name, str(error))

def equal(actual, expected):
    assert actual == expected, f'{actual!r} != {expected!r}'

try:
    load(FEED, card(A, -1000) + card(B, modern=True))
    check('Every feed snapshot retains its own permalink', lambda: equal([x['resourceUrl'] for x in snapshots()], [url(A), url(B)]))
    check('Modern visible feed player resolves B', lambda: equal(resolved().get('url'), url(B)))
    check('Active DOM target selects B rather than preload A', lambda: equal(driver.execute_script('return KittyMediaDOM.selection().domId'), snapshots()[1]['domId']))
    load(url(A), card(B))
    check('SPA current player wins over old address-bar permalink', lambda: equal(resolved().get('url'), url(B)))
    load(FEED, card(B, wrong_link=C))
    check('Comment link cannot replace the current player ID', lambda: equal(resolved().get('url'), url(B)))
    check('Snapshot also rejects unrelated comment link', lambda: equal(snapshots()[0]['resourceUrl'], url(B)))
    load(FEED, card(A, hidden=True) + card(B, 40))
    check('Hidden preload cannot become the resolved video', lambda: equal(resolved().get('url'), url(B)))
    load(FEED, card(A, 20) + card(B, 80))
    driver.execute_script('Object.defineProperty(document.querySelectorAll("video")[1],"paused",{value:false});')
    check('Playing video wins over similarly visible paused preload', lambda: equal(resolved().get('url'), url(B)))
    load(FEED, '<video src="blob:https://www.tiktok.com/unknown"></video>')
    check('Unknown blob snapshot has no fabricated permalink', lambda: equal(snapshots()[0]['resourceUrl'], None))
    check('Unknown feed is rejected', lambda: equal(resolved()['ok'], False))
    for kind in ('embed/v2', 'player/v1'):
        load('https://www.tiktok.com/'+kind+'/'+B, '')
        check(kind+' canonicalization', lambda: equal(resolved().get('url'), 'https://www.tiktok.com/@_/video/'+B))
finally:
    driver.quit()
report['ok'] = not report['failures']
output = Path(os.environ.get('KITTY_TIKTOK_REPORT', ROOT / 'artifacts/tiktok/firefox.json'))
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
print(f"TikTok Firefox: {len(report['checks'])} passed, {len(report['failures'])} failed")
sys.exit(0 if report['ok'] else 1)
