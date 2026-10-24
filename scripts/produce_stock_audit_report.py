"""Render reviewed dated research and verify the established Stock Audit format."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from bs4 import BeautifulSoup

sys.path.insert(0,str(Path(__file__).resolve().parent))
from render_stock_audit import complete_stock, render


def format_signature(html):
    """Compare component contracts, not data-dependent text or chart geometry."""
    soup=BeautifulSoup(html,'html.parser')
    cards=[]
    for card in soup.select('details.stock'):
        body=card.select_one('.stock-body')
        cards.append({
            'open':card.has_attr('open'),
            'children':[(el.name,tuple(el.get('class',[]))) for el in body.find_all(recursive=False)] if body else [],
            'headings':[''.join(h.find_all(string=True,recursive=False)).strip() for h in card.select('h3,h4')],
            'methods':[''.join(el.select_one('h4').find_all(string=True,recursive=False)).strip() if el.select_one('h4') else el.get('class') for el in card.select('.method-summary')],
            'tables':[[th.get_text(' ',strip=True) for th in table.select('thead th')] for table in card.select('table.entry-plan')],
            'chart_count':len(card.select('svg[role="img"]')),
            'analysis_closed':all(not el.has_attr('open') for el in card.select('details.analysis')),
        })
    return {
        'sections':[(s.get('id'),s.find('h2').get_text(' ',strip=True)) for s in soup.select('main > section')],
        'styles':[l.get('href') for l in soup.select('link[rel="stylesheet"]')],
        'cards':cards,
    }


def same_format(baseline,candidate):
    left=format_signature(baseline);right=format_signature(candidate)
    left_cards=left.pop('cards');right_cards=right.pop('cards')
    return (left==right and 3<=len(right_cards)<=5 and bool(left_cards)
            and all(card in left_cards for card in right_cards))


def produce(data,baseline,output_dir):
    if data.get('research_status')!='reviewed':
        raise ValueError('Only fully reviewed research can be produced')
    day=data['report_date']
    if not 3<=len(data['stocks'])<=5 or not all(complete_stock(s,day,data.get('forecast_cutoff')) for s in data['stocks']):
        raise ValueError('Every selected stock must be complete; no silent exclusion')
    if 'economic_events' not in data['market'] or not isinstance(data['market']['economic_events'],list):
        raise ValueError('Explicit current economic_events review required')
    data=dict(data,source_json_filename=f'stock-audit-{day}.json')
    html=render(data)
    if not same_format(baseline.read_text(),html):
        raise ValueError('Report format differs from approved baseline')
    css=baseline.parent/'stock-audit.css'
    if not css.is_file():raise ValueError('Baseline stylesheet missing')
    canonical_css=Path(__file__).resolve().parents[1]/'reports/stock-audit.css'
    if css.read_bytes()!=canonical_css.read_bytes():
        raise ValueError('Baseline stylesheet differs from the shared renderer stylesheet')
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    html_path=output_dir/f'stock-audit-{day}.html'
    json_path=html_path.with_suffix('.json')
    if html_path.exists() or json_path.exists():
        raise ValueError('Dated output exists; choose an empty staging directory')
    existing_css=output_dir/css.name
    if existing_css.exists() and existing_css.read_bytes()!=css.read_bytes():
        raise ValueError('Output stylesheet differs from baseline')
    snapshot=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if css.resolve()!=existing_css.resolve():shutil.copyfile(css,existing_css)
    json_path.write_text(snapshot);html_path.write_text(html)
    return dict(report_date=day,stocks=len(data['stocks']),structural_format='PASS',
                stylesheet_sha256=hashlib.sha256(css.read_bytes()).hexdigest(),
                html_sha256=hashlib.sha256(html.encode()).hexdigest(),html=str(html_path),json=str(json_path))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(produce(json.loads(args.input.read_text()),args.baseline,args.output_dir),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
