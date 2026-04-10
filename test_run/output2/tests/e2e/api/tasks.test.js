/**
 * E2E Tests — Task Tracker API
 * Real HTTP calls, no mocks.
 * Run: node tests/e2e/api/tasks.test.js
 */

const BASE = 'http://localhost:9876';

let passed = 0;
let failed = 0;
const results = { passed: [], failed: [] };

async function req(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  let json;
  try { json = await res.json(); } catch { json = null; }
  return { status: res.status, body: json };
}

function assert(condition, msg) {
  if (!condition) throw new Error(`Assertion failed: ${msg}`);
}

async function test(name, fn) {
  try {
    await fn();
    passed++;
    results.passed.push(name);
    console.log(`  PASS  ${name}`);
  } catch (e) {
    failed++;
    results.failed.push({ name, error: e.message });
    console.log(`  FAIL  ${name}: ${e.message}`);
  }
}

// ─── State shared across tests ───────────────────────────────────────────────
let tokenA, tokenB, userAId, userBId;
let taskId; // created by User A

// ─── 1. Auth ─────────────────────────────────────────────────────────────────
async function runAuthTests() {
  console.log('\n=== Auth Tests ===');

  await test('register User A → 201 with id/email/name/created_at', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'testa_e2e@example.com',
      password: 'TestPass1',
      name: 'User A',
    });
    assert(r.status === 201, `expected 201 got ${r.status}`);
    assert(r.body.id, 'missing id');
    assert(r.body.email === 'testa_e2e@example.com', 'wrong email');
    assert(r.body.name === 'User A', 'wrong name');
    assert(r.body.created_at, 'missing created_at');
    userAId = r.body.id;
  });

  await test('register User B → 201', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'testb_e2e@example.com',
      password: 'TestPass2',
      name: 'User B',
    });
    assert(r.status === 201, `expected 201 got ${r.status}`);
    userBId = r.body.id;
  });

  await test('duplicate email → 409', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'testa_e2e@example.com',
      password: 'TestPass1',
      name: 'User A Again',
    });
    assert(r.status === 409, `expected 409 got ${r.status}`);
  });

  await test('BR-001: password too short → 400', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'weak1@example.com',
      password: 'short',
      name: 'Weak',
    });
    assert(r.status === 400, `expected 400 got ${r.status}`);
  });

  await test('BR-001: password missing uppercase → 400', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'weak2@example.com',
      password: 'alllower1',
      name: 'Weak',
    });
    assert(r.status === 400, `expected 400 got ${r.status}`);
  });

  await test('BR-001: password missing digit → 400', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'weak3@example.com',
      password: 'NoDigitHere',
      name: 'Weak',
    });
    assert(r.status === 400, `expected 400 got ${r.status}`);
  });

  await test('login User A → 200 with token', async () => {
    const r = await req('POST', '/api/auth/login', {
      email: 'testa_e2e@example.com',
      password: 'TestPass1',
    });
    assert(r.status === 200, `expected 200 got ${r.status}`);
    assert(r.body.token, 'missing token');
    assert(r.body.user && r.body.user.id, 'missing user');
    tokenA = r.body.token;
  });

  await test('login User B → 200 with token', async () => {
    const r = await req('POST', '/api/auth/login', {
      email: 'testb_e2e@example.com',
      password: 'TestPass2',
    });
    assert(r.status === 200, `expected 200 got ${r.status}`);
    tokenB = r.body.token;
  });

  await test('invalid credentials → 401', async () => {
    const r = await req('POST', '/api/auth/login', {
      email: 'testa_e2e@example.com',
      password: 'WrongPassword1',
    });
    assert(r.status === 401, `expected 401 got ${r.status}`);
  });
}

// ─── 2. Tasks CRUD ────────────────────────────────────────────────────────────
async function runTaskCrudTests() {
  console.log('\n=== Tasks CRUD Tests ===');

  await test('POST /api/tasks → 201, status=PENDING, verify with GET', async () => {
    const r = await req('POST', '/api/tasks', {
      title: 'My First Task',
      description: 'Test description',
      priority: 'HIGH',
    }, tokenA);
    assert(r.status === 201, `expected 201 got ${r.status}`);
    assert(r.body.id, 'missing id');
    assert(r.body.title === 'My First Task', 'wrong title');
    assert(r.body.status === 'PENDING', `expected PENDING got ${r.body.status}`);
    assert(r.body.priority === 'HIGH', `expected HIGH got ${r.body.priority}`);
    assert(r.body.user_id, 'missing user_id');
    taskId = r.body.id;
    // Verify with GET
    const g = await req('GET', `/api/tasks/${taskId}`, null, tokenA);
    assert(g.status === 200, `GET verify failed: ${g.status}`);
    assert(g.body.id === taskId, 'GET returned wrong task');
  });

  await test('GET /api/tasks → 200, tasks array contains created task', async () => {
    const r = await req('GET', '/api/tasks', null, tokenA);
    assert(r.status === 200, `expected 200 got ${r.status}`);
    assert(Array.isArray(r.body.tasks), 'expected tasks array');
    const found = r.body.tasks.find(t => t.id === taskId);
    assert(found, 'created task not in list');
  });

  await test('GET /api/tasks/:id → 200, correct task', async () => {
    const r = await req('GET', `/api/tasks/${taskId}`, null, tokenA);
    assert(r.status === 200, `expected 200 got ${r.status}`);
    assert(r.body.id === taskId, 'wrong id');
    assert(r.body.title === 'My First Task', 'wrong title');
  });

  await test('PATCH /api/tasks/:id → 200, title updated, verify with GET', async () => {
    const r = await req('PATCH', `/api/tasks/${taskId}`, { title: 'Updated Title' }, tokenA);
    assert(r.status === 200, `expected 200 got ${r.status}`);
    assert(r.body.title === 'Updated Title', `expected updated title got ${r.body.title}`);
    // Verify with GET
    const g = await req('GET', `/api/tasks/${taskId}`, null, tokenA);
    assert(g.body.title === 'Updated Title', 'GET did not reflect update');
  });

  await test('PATCH /api/tasks/:id — valid status transition PENDING→IN_PROGRESS', async () => {
    const r = await req('PATCH', `/api/tasks/${taskId}`, { status: 'IN_PROGRESS' }, tokenA);
    assert(r.status === 200, `expected 200 got ${r.status}`);
    assert(r.body.status === 'IN_PROGRESS', `expected IN_PROGRESS got ${r.body.status}`);
    // Verify
    const g = await req('GET', `/api/tasks/${taskId}`, null, tokenA);
    assert(g.body.status === 'IN_PROGRESS', 'GET did not reflect status change');
  });

  await test('PATCH /api/tasks/:id — valid transition IN_PROGRESS→DONE', async () => {
    const r = await req('PATCH', `/api/tasks/${taskId}`, { status: 'DONE' }, tokenA);
    assert(r.status === 200, `expected 200 got ${r.status}`);
    assert(r.body.status === 'DONE', `expected DONE got ${r.body.status}`);
  });

  await test('DELETE /api/tasks/:id → 200 message, verify with GET → 404', async () => {
    const r = await req('DELETE', `/api/tasks/${taskId}`, null, tokenA);
    assert(r.status === 200, `expected 200 got ${r.status}`);
    assert(r.body.message, 'missing message');
    // Verify with GET — should 404
    const g = await req('GET', `/api/tasks/${taskId}`, null, tokenA);
    assert(g.status === 404, `expected 404 after delete got ${g.status}`);
  });

  await test('BR-005: soft delete — deleted task not in GET /api/tasks list', async () => {
    // Create a fresh task then delete it
    const c = await req('POST', '/api/tasks', { title: 'To Delete' }, tokenA);
    const id = c.body.id;
    await req('DELETE', `/api/tasks/${id}`, null, tokenA);
    const list = await req('GET', '/api/tasks', null, tokenA);
    const found = list.body.tasks.find(t => t.id === id);
    assert(!found, 'deleted task still appears in list');
  });
}

// ─── 3. Business Rules ────────────────────────────────────────────────────────
async function runBusinessRuleTests() {
  console.log('\n=== Business Rules Tests ===');

  // Create a fresh task for BR tests
  let brTaskId;
  await test('setup: create task for BR tests', async () => {
    const r = await req('POST', '/api/tasks', { title: 'BR Test Task', priority: 'LOW' }, tokenA);
    assert(r.status === 201, `setup failed: ${r.status}`);
    brTaskId = r.body.id;
  });

  await test('BR-002: IDOR — User B GET User A task → 403', async () => {
    const r = await req('GET', `/api/tasks/${brTaskId}`, null, tokenB);
    assert(r.status === 403 || r.status === 404, `expected 403/404 got ${r.status}`);
  });

  await test('BR-002: IDOR — User B PATCH User A task → 403', async () => {
    const r = await req('PATCH', `/api/tasks/${brTaskId}`, { title: 'Hijacked' }, tokenB);
    assert(r.status === 403 || r.status === 404, `expected 403/404 got ${r.status}`);
    // Verify title unchanged
    const g = await req('GET', `/api/tasks/${brTaskId}`, null, tokenA);
    assert(g.body.title === 'BR Test Task', `title was changed by user B: ${g.body.title}`);
  });

  await test('BR-002: IDOR — User B DELETE User A task → 403', async () => {
    const r = await req('DELETE', `/api/tasks/${brTaskId}`, null, tokenB);
    assert(r.status === 403 || r.status === 404, `expected 403/404 got ${r.status}`);
    // Verify still exists
    const g = await req('GET', `/api/tasks/${brTaskId}`, null, tokenA);
    assert(g.status === 200, 'task was deleted by user B');
  });

  await test('BR-003: empty title → 400', async () => {
    const r = await req('POST', '/api/tasks', { title: '' }, tokenA);
    assert(r.status === 400, `expected 400 got ${r.status}`);
  });

  await test('BR-003: whitespace-only title → 400', async () => {
    const r = await req('POST', '/api/tasks', { title: '   ' }, tokenA);
    assert(r.status === 400, `expected 400 got ${r.status}`);
  });

  await test('BR-004: invalid transition PENDING→DONE → 400', async () => {
    // brTaskId is PENDING
    const r = await req('PATCH', `/api/tasks/${brTaskId}`, { status: 'DONE' }, tokenA);
    assert(r.status === 400, `expected 400 got ${r.status}`);
  });

  await test('BR-004: invalid transition (move to IN_PROGRESS then try DONE→IN_PROGRESS) → 400', async () => {
    // move to IN_PROGRESS first
    await req('PATCH', `/api/tasks/${brTaskId}`, { status: 'IN_PROGRESS' }, tokenA);
    await req('PATCH', `/api/tasks/${brTaskId}`, { status: 'DONE' }, tokenA);
    // Now DONE → IN_PROGRESS is invalid
    const r = await req('PATCH', `/api/tasks/${brTaskId}`, { status: 'IN_PROGRESS' }, tokenA);
    assert(r.status === 400, `expected 400 got ${r.status}`);
  });
}

// ─── 4. Filters ───────────────────────────────────────────────────────────────
async function runFilterTests() {
  console.log('\n=== Filter Tests ===');

  await test('filter by status=PENDING returns only PENDING tasks', async () => {
    // Create a PENDING task
    await req('POST', '/api/tasks', { title: 'Filter PENDING', priority: 'MEDIUM' }, tokenA);
    const r = await req('GET', '/api/tasks?status=PENDING', null, tokenA);
    assert(r.status === 200, `expected 200 got ${r.status}`);
    assert(Array.isArray(r.body.tasks), 'expected array');
    for (const t of r.body.tasks) {
      assert(t.status === 'PENDING', `task with status ${t.status} returned for PENDING filter`);
    }
  });

  await test('filter by priority=LOW returns only LOW priority tasks', async () => {
    await req('POST', '/api/tasks', { title: 'Low Priority Task', priority: 'LOW' }, tokenA);
    const r = await req('GET', '/api/tasks?priority=LOW', null, tokenA);
    assert(r.status === 200, `expected 200 got ${r.status}`);
    assert(Array.isArray(r.body.tasks), 'expected array');
    for (const t of r.body.tasks) {
      assert(t.priority === 'LOW', `task with priority ${t.priority} returned for LOW filter`);
    }
  });
}

// ─── 5. Auth Required ─────────────────────────────────────────────────────────
async function runAuthRequiredTests() {
  console.log('\n=== Auth Required Tests ===');

  const fakeId = '00000000-0000-0000-0000-000000000000';

  await test('GET /api/tasks without token → 401', async () => {
    const r = await req('GET', '/api/tasks');
    assert(r.status === 401, `expected 401 got ${r.status}`);
  });

  await test('POST /api/tasks without token → 401', async () => {
    const r = await req('POST', '/api/tasks', { title: 'No Auth' });
    assert(r.status === 401, `expected 401 got ${r.status}`);
  });

  await test('GET /api/tasks/:id without token → 401', async () => {
    const r = await req('GET', `/api/tasks/${fakeId}`);
    assert(r.status === 401, `expected 401 got ${r.status}`);
  });

  await test('PATCH /api/tasks/:id without token → 401', async () => {
    const r = await req('PATCH', `/api/tasks/${fakeId}`, { title: 'x' });
    assert(r.status === 401, `expected 401 got ${r.status}`);
  });

  await test('DELETE /api/tasks/:id without token → 401', async () => {
    const r = await req('DELETE', `/api/tasks/${fakeId}`);
    assert(r.status === 401, `expected 401 got ${r.status}`);
  });
}

// ─── Main ─────────────────────────────────────────────────────────────────────
(async () => {
  console.log('Task Tracker API — E2E Tests');
  console.log(`Base URL: ${BASE}\n`);

  try {
    await runAuthTests();
    await runTaskCrudTests();
    await runBusinessRuleTests();
    await runFilterTests();
    await runAuthRequiredTests();
  } catch (e) {
    console.error('Fatal error in test runner:', e.message);
  }

  const total = passed + failed;
  console.log(`\n========================================`);
  console.log(`Total: ${total} | Passed: ${passed} | Failed: ${failed}`);
  console.log(`========================================`);

  if (results.failed.length > 0) {
    console.log('\nFailed tests:');
    for (const f of results.failed) {
      console.log(`  - ${f.name}: ${f.error}`);
    }
  }

  // Write results summary to a file for STEP 9
  const fs = await import('fs');
  const summary = {
    total,
    passed,
    failed,
    passedTests: results.passed,
    failedTests: results.failed,
  };
  fs.writeFileSync('C:/Projects/agent-team-v15/test_run/output2/.agent-team/e2e_run_results.json',
    JSON.stringify(summary, null, 2));

  process.exit(failed > 0 ? 1 : 0);
})();
