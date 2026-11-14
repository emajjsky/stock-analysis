"""Check the reference stock's separated chip lines and independent price labels."""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = 'http://127.0.0.1:8765'
OUT = Path(__file__).resolve().parents[1] / 'docs/evidence/stock-sidebar-density'


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel='msedge')
    page = browser.new_page(viewport={'width':1366,'height':900}, device_scale_factor=2)
    errors, results = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    for key in ['LIVE.SZ.000019', 'LIVE.SZ.300502', 'LIVE.SZ.000014']:
        page.goto(BASE+'/#/stock/'+key, wait_until='networkidle')
        page.get_by_role('button', name='日 K', exact=True).click()
        page.get_by_role('tab', name='筹码分布', exact=True).click()
        expect(page.locator('.chip-track i').first).to_be_visible(timeout=20000)
        for width in [1366,390]:
            page.set_viewport_size({'width':width,'height':900})
            page.wait_for_timeout(150)
            metrics = page.locator('.chip-profile').evaluate('''el=>{
                const rows=[...el.querySelectorAll('.chip-row')];
                const tracks=rows.map(row=>row.querySelector('.chip-track').getBoundingClientRect());
                const bars=rows.map(row=>row.querySelector('i').getBoundingClientRect());
                return {rowCount:rows.length, pitches:tracks.slice(1).map((r,i)=>r.top-tracks[i].top),
                    barHeights:bars.map(r=>r.height), barGaps:bars.slice(1).map((r,i)=>r.top-bars[i].bottom),
                    labelPositions:rows.filter(row=>row.querySelector('.chip-price').textContent)
                        .map(row=>getComputedStyle(row.querySelector('.chip-price')).position),
                    visibleBars:bars.filter(r=>r.width>=1).length,
                    horizontalOverflow:el.scrollWidth>el.clientWidth+1};
            }''')
            assert metrics['rowCount'] == 140, metrics
            assert all(abs(value-2)<0.01 for value in metrics['pitches']), metrics
            assert all(abs(value-1)<0.01 for value in metrics['barHeights']), metrics
            assert all(abs(value-1)<0.01 for value in metrics['barGaps']), metrics
            assert set(metrics['labelPositions']) == {'absolute'}, metrics
            assert metrics['visibleBars']>50 and not metrics['horizontalOverflow'], metrics
            results.append({'key':key,'width':width,'visibleBars':metrics['visibleBars'],
                            'barHeight':1,'barGap':1,'pitch':2,'labelsIndependent':True})
            if key=='LIVE.SZ.000019':
                page.locator('.chip-panel').screenshot(path=str(OUT/f'chip-000019-lines-{width}.png'))
    assert not errors, errors
    browser.close()
    (OUT/'chip-lines-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
