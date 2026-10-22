"""AC B/C/D/E: execute the actual TypeScript boundary, not source-string copies.

The committed source-backed payload is the baseline; mutations are test-only.
External collection is not mocked as proven here (separate live receipts/browser).
"""
import json
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope='module')
def compiled_service(tmp_path_factory):
    out=tmp_path_factory.mktemp('audit-service')
    subprocess.run([str(ROOT/'node_modules/.bin/tsc'),str(ROOT/'src/services/stockAudit.ts'),
                    '--target','ES2020','--module','commonjs','--moduleResolution','node',
                    '--strict','--skipLibCheck','--outDir',str(out)],check=True,cwd=ROOT,capture_output=True,text=True)
    return out/'stockAudit.js'


def run(compiled_service, body):
    script=f"""
const assert=require('node:assert/strict');
const {{validateStockAuditReport:validate}}=require({json.dumps(str(compiled_service))});
const original=JSON.parse(require('node:fs').readFileSync('data/stock-audit-latest.json'));
const fresh=()=>structuredClone(original);
{body}
"""
    result=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_actual_source_payload_and_post_selection_quality_not_threshold_gate(compiled_service):
    run(compiled_service,"""
const actual=validate(fresh());
assert.equal(actual.stocks.length,1); assert.equal(actual.stocks[0].price,245);
assert.equal(actual.forecast.references.length,7);
const low=fresh(); low.stocks[0].quality.sharpe=-100; low.stocks[0].quality.sortino=-100;
assert.equal(validate(low).stocks.length,1,'poor growth diagnostics must not become a fundamentals gate');
""")


def test_every_required_stock_field_is_fail_closed_and_no_recommendation_leaks(compiled_service):
    run(compiled_service,"""
for(const path of ['price','price_as_of','fundamentals.revenue','fundamentals.eps','fundamentals.pe',
 'valuation.premium_pct','valuation.source','technical.candles','operations','quality']) {
 const p=fresh();p.conclusion='鴻海 should never leak after exclusion';
 const keys=path.split('.');let node=p.stocks[0];while(keys.length>1)node=node[keys.shift()];delete node[keys[0]];
 const result=validate(p);assert.equal(result.stocks.length,0,path);
 assert.ok(!result.conclusion.includes('鴻海'),path);
}
const p=fresh();p.stocks[0].fundamentals.analysis='pending verification';
assert.equal(validate(p).stocks.length,0);
""")


def test_dates_future_quotes_and_arithmetic_corruption_are_rejected(compiled_service):
    run(compiled_service,"""
const invalid=fresh();invalid.report_date='2026-02-31';assert.throws(()=>validate(invalid));
for(const mutate of [
 p=>p.report_date='2020-01-01',
 p=>{p.stocks[0].price_as_of='2099-01-01T13:30:00+08:00';p.stocks[0].technical.candles.at(-1).date='2099-01-01'},
 p=>p.stocks[0].technical.support=1,
 p=>p.stocks[0].technical.ma20=1,
 p=>p.stocks[0].valuation.premium_pct=99,
 p=>p.stocks[0].operations[0].stop=9999,
 p=>p.stocks[0].technical.candles.at(-1).volume=-1,
 p=>p.stocks[0].technical.candles.at(-1).high=1,
]) {const p=fresh();mutate(p);assert.equal(validate(p).stocks.length,0);}
""")


def test_forecast_requires_all_reference_categories_and_trustworthy_clocks(compiled_service):
    run(compiled_service,"""
for(const mutate of [
 p=>p.forecast.references=p.forecast.references.filter(r=>!r.label.includes('台指期')),
 p=>p.forecast.references=p.forecast.references.filter(r=>!['Apple','Microsoft','NVIDIA'].some(n=>r.label.includes(n))),
 p=>p.forecast.references[0].as_of='2099-01-01T00:00:00Z'
]) {const p=fresh();mutate(p);assert.equal(validate(p).forecast,null);assert.equal(validate(p).stocks.length,1);}
""")


def test_invalid_provenance_is_not_silently_removed(compiled_service):
    run(compiled_service,"""
const p=fresh();p.source_receipts[0].fetched_at='2099-01-01T00:00:00Z';
assert.throws(()=>validate(p));
const noReceipts=fresh();delete noReceipts.source_receipts;
assert.equal(validate(noReceipts).stocks.length,1);
""")
