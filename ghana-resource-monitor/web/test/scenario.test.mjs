import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { project, evsNeeded } from '../src/lib/scenario.js';

const vec = JSON.parse(readFileSync(new URL('../../tests/vectors/scenario.json', import.meta.url)));
const near = (a, b) => (a === null || b === null ? assert.equal(a, b) : assert.ok(Math.abs(a - b) < 1e-6, `${a} vs ${b}`));

for (const c of vec.cases) {
  test(`scenario vector: ${c.name}`, () => {
    const r = project(c.inputs);
    assert.equal(r.below_target_year, c.expect.below_target_year);
    assert.equal(r.gap_year, c.expect.gap_year);
    for (const e of c.expect.rows) {
      const got = r.rows.find((x) => x.year === e.year);
      for (const k of ['demand', 'ev_mw', 'total', 'available', 'margin']) near(got[k], e[k]);
    }
  });
}
test('evsNeeded matches Python', () => near(evsNeeded(...vec.evs_needed.args), vec.evs_needed.expect));
