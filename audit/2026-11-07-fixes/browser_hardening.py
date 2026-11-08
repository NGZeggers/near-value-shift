"""Offline browser edge cases and automated accessibility checks for phase 2."""
import functools
import tempfile
from unittest.mock import patch
from near_thesis import site
import http.server
import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

import os
ROOT=Path(os.environ.get('PHASE2_ROOT', Path(__file__).resolve().parents[2]))
OUT=Path(os.environ.get('PHASE2_OUT','/tmp/near-phase2-browser'))
OUT.mkdir(exist_ok=True)
AXE=Path(os.environ.get('PHASE2_AXE','/tmp/near-phase2-browser-tools/node_modules/axe-core/axe.min.js'))

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(ROOT/'site')))
threading.Thread(target=server.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{server.server_port}'
html=(ROOT/'site/index.html').read_text()
raw=(ROOT/'site/data.json').read_text()
spec=json.loads(raw)
checks=[];accessibility=[];blocked=[]
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base) or route.request.url.startswith('data:') else (blocked.append(route.request.url),route.abort())[-1])
    errors=[]
    page.on('pageerror',lambda err:errors.append(str(err)))
    for theme,width in [('light',1440),('dark',1440),('light',375)]:
        page.set_viewport_size({'width':width,'height':1000})
        page.goto(base)
        page.get_by_role('button',name=theme.title(),exact=True).click()
        page.add_script_tag(path=str(AXE))
        result=page.evaluate("async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','best-practice']},resultTypes:['violations','incomplete']})")
        accessibility.append({'page':'dashboard','theme':theme,'width':width,
            'violations':[{k:v[k] for k in ['id','impact','description','help','helpUrl','nodes']} for v in result['violations']],
            'incomplete_rules':[(v['id'],len(v['nodes'])) for v in result['incomplete']]})
        page.screenshot(path=str(OUT/f'dashboard-{theme}-{width}.png'),full_page=True)
    page.goto(base+'/walkthrough.html')
    page.add_script_tag(path=str(AXE))
    result=page.evaluate("async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','best-practice']},resultTypes:['violations']})")
    accessibility.append({'page':'notebook','violations':[{k:v[k] for k in ['id','impact','description','help','helpUrl','nodes']} for v in result['violations']]})
    # JSON data is raw text in an HTML script element, so test the HTML parser's
    # double-escaped script state in addition to direct closing-tag payloads.
    page.set_viewport_size({'width':1440,'height':1000})
    for label,payload in [('direct_close','</script><script>window.__phase2_xss=1</script>'),
                          ('comment_script','<!--<script>'),('unicode','\u2028\u2029<&')]:
        modified=json.loads(json.dumps(spec));modified['charts'][0]['title']=payload
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)
            (target/'data.json').write_text(json.dumps(modified))
            with patch.object(site, 'SITE', target):
                site.run()
            edge=(target/'index.html').read_text()
        before=len(errors);page.set_content(edge)
        checks.append({'name':label,'passed':page.locator('section.card').count()==len(spec['charts']) and page.evaluate('window.__phase2_xss===undefined'),
                       'cards':page.locator('section.card').count(),'javascript_errors':errors[before:]})
    with tempfile.TemporaryDirectory() as temp:
        target=Path(temp)
        (target/'data.json').write_text('{"value":Infinity}')
        (target/'index.html').write_text('previous page')
        try:
            with patch.object(site,'SITE',target):site.run()
        except ValueError:
            preserved=(target/'index.html').read_text()=='previous page'
        else:preserved=False
    checks.append({'name':'nonfinite_input_rejected_before_page_replace','passed':preserved})
    browser.close()
server.shutdown()
(OUT/'checks.json').write_text(json.dumps(checks,indent=2)+'\n')
(OUT/'accessibility.json').write_text(json.dumps(accessibility,indent=2)+'\n')
(OUT/'blocked-external-requests.json').write_text(json.dumps(sorted(set(blocked)),indent=2)+'\n')
print(json.dumps({'checks':checks,'accessibility':[{**{k:v for k,v in x.items() if k!='violations'},'violations':[(v['id'],v['impact'],len(v['nodes'])) for v in x['violations']]} for x in accessibility],
                  'blocked_external_requests':len(set(blocked))},indent=2))
