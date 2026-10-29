"""Browser-rendered UI capture using real backend-generated API fixtures.

Requires an already-running RackHelm app and optional Playwright:
    pip install -e '.[screenshots]'
    playwright install chromium
    python scripts/capture_dashboard.py
The browser environment here blocks HTTP requests, so the script injects
responses captured from the real FastAPI server. This is not a live-site test.
"""

import json
import os
import shutil
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
web=root/'src/rackhelm/web'
screen=root/'docs/screenshots'
screen.mkdir(parents=True,exist_ok=True)
html=(web/'index.html').read_text().replace('<link rel="stylesheet" href="/assets/styles.css">','').replace('<script src="/assets/app.js" defer></script>','')
css=(web/'styles.css').read_text()
js=(web/'app.js').read_text()
host=os.environ.get('RACKHELM_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
def get(path):
    with urlopen(host+path,timeout=12) as r:
        return json.load(r)

overview=get('/api/v1/overview')
incidents=get('/api/v1/incidents')
histories={r['rack_id']: get('/api/v1/racks/'+r['rack_id']+'/history?limit=36') for r in overview['racks']}
scenario_default=get('/api/v1/scenario?zone=Z02&cooling_drop_pct=30&gpu_load_delta_pct=15&setpoint_delta_c=0')
scenario_custom=get('/api/v1/scenario?zone=Z03&cooling_drop_pct=90&gpu_load_delta_pct=15&setpoint_delta_c=0')
fixtures={'overview':overview,'incidents':incidents,'histories':histories,'scenarios':{'Z02/30/15/0':scenario_default,'Z03/90/15/0':scenario_custom}}
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=shutil.which('chromium') or None,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    page=browser.new_page(viewport={'width':1560,'height':1030},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda exc: errors.append(str(exc)))
    page.set_content(html,wait_until='domcontentloaded')
    page.add_style_tag(content=css)
    page.evaluate('''(data) => {
      const fixtures = data;
      window.fetch = async (raw) => {
        const url = new URL(raw, 'https://fake-local.example');
        let result, status=200;
        if(url.pathname === '/api/v1/overview') result = fixtures.overview;
        else if(url.pathname === '/api/v1/incidents') result = fixtures.incidents;
        else if(url.pathname.endsWith('/history')) result = fixtures.histories[url.pathname.split('/')[4]];
        else if(url.pathname === '/api/v1/scenario') {
          const q=url.searchParams;
          const key=[q.get('zone'),q.get('cooling_drop_pct'),q.get('gpu_load_delta_pct'),q.get('setpoint_delta_c')].join('/');
          result=fixtures.scenarios[key];
        }
        if(!result){ status=404;result={detail:'Fixture not available for '+url.pathname}; }
        return new Response(JSON.stringify(result), {status, headers:{'Content-Type':'application/json'}});
      };
    }''', fixtures)
    page.add_script_tag(content=js)
    page.locator('.rack-tile').first.wait_for(timeout=12000)
    page.wait_for_timeout(550)
    print('title:',page.title())
    print('visible racks:',page.locator('.rack-tile').count())
    print('selected rack:',page.locator('#selected-rack-heading').inner_text())
    print('risk:',page.locator('#selected-risk').inner_text())
    print('scenario:',page.locator('#scenario-temp').inner_text())
    print('JS errors:',errors)
    assert page.locator('.rack-tile').count()==12
    assert page.locator('#selected-rack-heading').inner_text()=='Z02-R04'
    assert not errors
    page.screenshot(path=str(screen/'rackhelm-dashboard.png'),full_page=True)
    page.locator('.heat-panel').screenshot(path=str(screen/'thermal-heatmap.png'))
    page.locator('#simulation').screenshot(path=str(screen/'cooling-whatif.png'))
    page.get_by_role('button',name='ZONE 03').click()
    assert page.locator('.rack-tile').count()==12
    page.locator('.rack-tile').last.click()
    page.wait_for_timeout(50)
    assert page.locator('#selected-rack-heading').inner_text().startswith('Z03')
    page.locator('#cooling-loss').fill('90')
    page.locator('#simulate-btn').click()
    page.wait_for_timeout(80)
    print('scenario after slider:',page.locator('#scenario-temp').inner_text())
    assert page.locator('#scenario-temp').inner_text() == str(round(scenario_custom['estimated_peak_inlet_c'],1))
    assert not errors
    browser.close()
print('Screenshots in',screen)