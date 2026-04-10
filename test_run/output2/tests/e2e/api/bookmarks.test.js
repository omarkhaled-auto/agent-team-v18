/**
 * E2E Tests — Bookmark API
 * Real HTTP calls against running Express server, no mocks.
 * Run: npm run build && npm run dev (in separate terminal) PORT=9876, then: node tests/e2e/api/bookmarks.test.js
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
    console.log(`  ✓  ${name}`);
  } catch (e) {
    failed++;
    results.failed.push({ name, error: e.message });
    console.log(`  ✗  ${name}: ${e.message}`);
  }
}

// ─── Shared state across tests ───────────────────────────────────────────────
let tokenA, tokenB, userAId, userBId;
let bookmarkA1Id, bookmarkA2Id, bookmarkB1Id; // IDs created during tests for state machine

// ─── 1. Auth Tests ───────────────────────────────────────────────────────────

async function runAuthTests() {
  console.log('\n=== AUTH TESTS ===');

  await test('REQ-006: Register User A → 201, returns id/email/name/created_at', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'user-a@example.com',
      password: 'Password123',
      name: 'User A',
    });
    assert(r.status === 201, `Expected 201, got ${r.status}`);
    assert(r.body.id, 'Missing id');
    assert(r.body.email === 'user-a@example.com', 'Email mismatch');
    assert(r.body.name === 'User A', 'Name mismatch');
    assert(r.body.created_at, 'Missing created_at');
    userAId = r.body.id;
  });

  await test('REQ-006: Register User B → 201', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'user-b@example.com',
      password: 'Password456',
      name: 'User B',
    });
    assert(r.status === 201, `Expected 201, got ${r.status}`);
    assert(r.body.id, 'Missing id');
    userBId = r.body.id;
  });

  await test('REQ-006: Duplicate email → 409', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'user-a@example.com',
      password: 'Password999',
      name: 'Duplicate',
    });
    assert(r.status === 409, `Expected 409, got ${r.status}`);
    assert(r.body.error === true, 'Expected error flag');
  });

  await test('REQ-007: Password < 8 chars → 400', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'short@example.com',
      password: 'Pas1',
      name: 'Short Password',
    });
    assert(r.status === 400, `Expected 400, got ${r.status}`);
    assert(r.body.error === true, 'Expected error flag');
  });

  await test('REQ-007: Password missing uppercase → 400', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'noupper@example.com',
      password: 'password123',
      name: 'No Upper',
    });
    assert(r.status === 400, `Expected 400, got ${r.status}`);
  });

  await test('REQ-007: Password missing digit → 400', async () => {
    const r = await req('POST', '/api/auth/register', {
      email: 'nodigit@example.com',
      password: 'PasswordABC',
      name: 'No Digit',
    });
    assert(r.status === 400, `Expected 400, got ${r.status}`);
  });

  await test('REQ-008: Login User A → 200, returns token', async () => {
    const r = await req('POST', '/api/auth/login', {
      email: 'user-a@example.com',
      password: 'Password123',
    });
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    assert(r.body.token, 'Missing token');
    assert(r.body.user.id === userAId, 'User ID mismatch');
    assert(r.body.user.email === 'user-a@example.com', 'Email mismatch');
    tokenA = r.body.token;
  });

  await test('REQ-008: Login User B → 200, returns token', async () => {
    const r = await req('POST', '/api/auth/login', {
      email: 'user-b@example.com',
      password: 'Password456',
    });
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    assert(r.body.token, 'Missing token');
    tokenB = r.body.token;
  });

  await test('REQ-008: Invalid credentials → 401', async () => {
    const r = await req('POST', '/api/auth/login', {
      email: 'user-a@example.com',
      password: 'WrongPassword',
    });
    assert(r.status === 401, `Expected 401, got ${r.status}`);
  });

  await test('REQ-008: Login non-existent user → 401', async () => {
    const r = await req('POST', '/api/auth/login', {
      email: 'nonexistent@example.com',
      password: 'Password123',
    });
    assert(r.status === 401, `Expected 401, got ${r.status}`);
  });
}

// ─── 2. Bookmark CRUD Tests ───────────────────────────────────────────────────

async function runBookmarkCrudTests() {
  console.log('\n=== BOOKMARK CRUD TESTS ===');

  await test('REQ-012: POST /api/bookmarks → 201, state=ACTIVE', async () => {
    const r = await req('POST', '/api/bookmarks', {
      url: 'https://example.com',
      title: 'Example Site',
      tags: JSON.stringify(['tech', 'web']),
    }, tokenA);
    assert(r.status === 201, `Expected 201, got ${r.status}`);
    assert(r.body.id, 'Missing id');
    assert(r.body.user_id === userAId, 'User ID mismatch');
    assert(r.body.url === 'https://example.com', 'URL mismatch');
    assert(r.body.title === 'Example Site', 'Title mismatch');
    assert(r.body.state === 'ACTIVE', 'Initial state should be ACTIVE');
    assert(r.body.created_at, 'Missing created_at');
    bookmarkA1Id = r.body.id;
  });

  await test('REQ-012: Create bookmark with no tags → 201', async () => {
    const r = await req('POST', '/api/bookmarks', {
      url: 'https://github.com',
      title: 'GitHub',
    }, tokenA);
    assert(r.status === 201, `Expected 201, got ${r.status}`);
    assert(r.body.id, 'Missing id');
    bookmarkA2Id = r.body.id;
  });

  await test('REQ-013: GET /api/bookmarks → 200, returns array', async () => {
    const r = await req('GET', '/api/bookmarks', null, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    assert(Array.isArray(r.body.bookmarks), 'Expected bookmarks array');
    assert(r.body.bookmarks.length >= 2, 'Should have at least 2 bookmarks');
    const found = r.body.bookmarks.some(b => b.id === bookmarkA1Id);
    assert(found, 'Created bookmark A1 should be in list');
  });

  await test('REQ-016: GET /api/bookmarks/:id → 200, single bookmark', async () => {
    const r = await req('GET', `/api/bookmarks/${bookmarkA1Id}`, null, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    assert(r.body.id === bookmarkA1Id, 'ID mismatch');
    assert(r.body.title === 'Example Site', 'Title mismatch');
  });

  await test('REQ-016: GET non-existent bookmark → 404', async () => {
    const r = await req('GET', '/api/bookmarks/nonexistent', null, tokenA);
    assert(r.status === 404, `Expected 404, got ${r.status}`);
  });

  await test('REQ-014: PATCH /api/bookmarks/:id → 200, title updated, verify with GET', async () => {
    const r = await req('PATCH', `/api/bookmarks/${bookmarkA2Id}`, {
      title: 'GitHub - Where the world builds software',
    }, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    assert(r.body.title === 'GitHub - Where the world builds software', 'Title not updated');

    // Verify with GET
    const verify = await req('GET', `/api/bookmarks/${bookmarkA2Id}`, null, tokenA);
    assert(verify.status === 200, 'GET failed');
    assert(verify.body.title === 'GitHub - Where the world builds software', 'Title not persisted');
  });

  await test('REQ-014: PATCH /api/bookmarks/:id with new URL, verify with GET', async () => {
    const newUrl = 'https://github.com/search';
    const r = await req('PATCH', `/api/bookmarks/${bookmarkA2Id}`, {
      url: newUrl,
    }, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    assert(r.body.url === newUrl, 'URL not updated');

    // Verify with GET
    const verify = await req('GET', `/api/bookmarks/${bookmarkA2Id}`, null, tokenA);
    assert(verify.body.url === newUrl, 'URL not persisted');
  });

  await test('REQ-014: PATCH with new tags, verify normalization', async () => {
    const r = await req('PATCH', `/api/bookmarks/${bookmarkA2Id}`, {
      tags: JSON.stringify(['GITHUB', '  coding  ', 'GitHub']), // duplicates, mixed case, whitespace
    }, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    const tags = JSON.parse(r.body.tags);
    assert(tags.length === 2, `Expected 2 unique tags, got ${tags.length}`);
    assert(tags.includes('github'), 'Tags not lowercased');
    assert(tags.includes('coding'), 'Tags not trimmed');
    assert(!tags.some(t => t !== t.toLowerCase()), 'Tags not normalized');
  });
}

// ─── 3. Business Rules Tests ─────────────────────────────────────────────────

async function runBusinessRuleTests() {
  console.log('\n=== BUSINESS RULES TESTS ===');

  await test('REQ-017: User isolation — User B GET User A bookmark → 403', async () => {
    const r = await req('GET', `/api/bookmarks/${bookmarkA1Id}`, null, tokenB);
    assert(r.status === 403, `Expected 403, got ${r.status}`);
  });

  await test('REQ-017: User isolation — User B PATCH User A bookmark → 403', async () => {
    const r = await req('PATCH', `/api/bookmarks/${bookmarkA1Id}`, {
      title: 'Hacked!',
    }, tokenB);
    assert(r.status === 403, `Expected 403, got ${r.status}`);
    // Verify title not changed
    const verify = await req('GET', `/api/bookmarks/${bookmarkA1Id}`, null, tokenA);
    assert(verify.body.title === 'Example Site', 'Title should not have changed');
  });

  await test('REQ-017: User isolation — User B DELETE User A bookmark → 403', async () => {
    const r = await req('DELETE', `/api/bookmarks/${bookmarkA1Id}`, null, tokenB);
    assert(r.status === 403, `Expected 403, got ${r.status}`);
    // Verify bookmark still exists for User A
    const verify = await req('GET', `/api/bookmarks/${bookmarkA1Id}`, null, tokenA);
    assert(verify.status === 200, 'Bookmark should still exist');
  });

  await test('REQ-018: Duplicate URL same user → 409', async () => {
    const r = await req('POST', '/api/bookmarks', {
      url: 'https://example.com', // Already bookmarked by User A
      title: 'Another bookmark to example',
    }, tokenA);
    assert(r.status === 409, `Expected 409, got ${r.status}`);
    assert(r.body.error === true, 'Expected error flag');
  });

  await test('REQ-018: Duplicate URL different user → 201 (allowed)', async () => {
    // User B can bookmark same URL as User A
    const r = await req('POST', '/api/bookmarks', {
      url: 'https://example.com',
      title: 'Example (User B)',
    }, tokenB);
    assert(r.status === 201, `Expected 201 (User B can bookmark same URL), got ${r.status}`);
    bookmarkB1Id = r.body.id;
  });

  await test('REQ-019: Tag normalization — max 5 tags', async () => {
    const r = await req('POST', '/api/bookmarks', {
      url: 'https://example.org/tags',
      title: 'Tag test',
      tags: JSON.stringify(['a', 'b', 'c', 'd', 'e', 'f', 'g']), // 7 tags
    }, tokenA);
    assert(r.status === 201, `Expected 201, got ${r.status}`);
    const tags = JSON.parse(r.body.tags);
    assert(tags.length === 5, `Expected max 5 tags, got ${tags.length}`);
  });

  await test('REQ-020: URL validation — must start with http:// or https://', async () => {
    const r = await req('POST', '/api/bookmarks', {
      url: 'ftp://invalid.com',
      title: 'Invalid protocol',
    }, tokenA);
    assert(r.status === 400, `Expected 400, got ${r.status}`);
  });

  await test('REQ-020: URL validation — invalid URL format', async () => {
    const r = await req('POST', '/api/bookmarks', {
      url: 'not-a-url',
      title: 'Not a URL',
    }, tokenA);
    assert(r.status === 400, `Expected 400, got ${r.status}`);
  });

  await test('REQ-027: Empty title → 400', async () => {
    const r = await req('POST', '/api/bookmarks', {
      url: 'https://example.com/test',
      title: '',
    }, tokenA);
    assert(r.status === 400, `Expected 400, got ${r.status}`);
  });

  await test('REQ-027: Title > 200 chars → 400', async () => {
    const longTitle = 'x'.repeat(201);
    const r = await req('POST', '/api/bookmarks', {
      url: 'https://example.com/test',
      title: longTitle,
    }, tokenA);
    assert(r.status === 400, `Expected 400, got ${r.status}`);
  });
}

// ─── 4. State Machine Tests ──────────────────────────────────────────────────

async function runStateMachineTests() {
  console.log('\n=== STATE MACHINE TESTS ===');

  await test('REQ-022: Archive bookmark ACTIVE → ARCHIVED', async () => {
    const r = await req('PATCH', `/api/bookmarks/${bookmarkA1Id}/archive`, {}, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    assert(r.body.state === 'ARCHIVED', 'State should be ARCHIVED');

    // Verify with GET
    const verify = await req('GET', `/api/bookmarks/${bookmarkA1Id}`, null, tokenA);
    assert(verify.body.state === 'ARCHIVED', 'State not persisted');
  });

  await test('REQ-024: Invalid transition ARCHIVED → ACTIVE → 422', async () => {
    // Try to archive again (already archived)
    const r = await req('PATCH', `/api/bookmarks/${bookmarkA1Id}/archive`, {}, tokenA);
    assert(r.status === 422, `Expected 422, got ${r.status}`);
  });

  await test('REQ-023: Delete bookmark ARCHIVED → DELETED', async () => {
    const r = await req('DELETE', `/api/bookmarks/${bookmarkA1Id}`, {}, tokenA);
    assert(r.status === 204, `Expected 204, got ${r.status}`);

    // Verify 404 on GET
    const verify = await req('GET', `/api/bookmarks/${bookmarkA1Id}`, null, tokenA);
    assert(verify.status === 404, 'DELETED bookmark should return 404');
  });

  await test('REQ-024: Invalid transition ACTIVE → DELETED (must archive first) → 422', async () => {
    // Try to delete without archiving first
    const r = await req('DELETE', `/api/bookmarks/${bookmarkA2Id}`, {}, tokenA);
    assert(r.status === 422, `Expected 422, got ${r.status}`);
    assert(r.body.error === true, 'Expected error flag');

    // Verify bookmark still exists
    const verify = await req('GET', `/api/bookmarks/${bookmarkA2Id}`, null, tokenA);
    assert(verify.status === 200, 'Bookmark should still exist');
  });

  await test('REQ-025: DELETED bookmarks excluded from list', async () => {
    const r = await req('GET', '/api/bookmarks', null, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    const hasDeleted = r.body.bookmarks.some(b => b.id === bookmarkA1Id);
    assert(!hasDeleted, 'DELETED bookmark should not appear in list');
  });
}

// ─── 5. Tag Filtering Tests ──────────────────────────────────────────────────

async function runFilterTests() {
  console.log('\n=== FILTER TESTS ===');

  // Create bookmarks with different tags for filtering
  let techBookmarkId, musicBookmarkId;

  await test('Setup: Create bookmarks with distinct tags', async () => {
    const r1 = await req('POST', '/api/bookmarks', {
      url: 'https://nodejs.org',
      title: 'Node.js',
      tags: JSON.stringify(['tech', 'javascript']),
    }, tokenA);
    assert(r1.status === 201, 'Failed to create tech bookmark');
    techBookmarkId = r1.body.id;

    const r2 = await req('POST', '/api/bookmarks', {
      url: 'https://spotify.com',
      title: 'Spotify',
      tags: JSON.stringify(['music', 'streaming']),
    }, tokenA);
    assert(r2.status === 201, 'Failed to create music bookmark');
    musicBookmarkId = r2.body.id;
  });

  await test('REQ-013: Filter by tag → GET /api/bookmarks?tag=tech', async () => {
    const r = await req('GET', '/api/bookmarks?tag=tech', null, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    const hasTech = r.body.bookmarks.some(b => b.id === techBookmarkId);
    assert(hasTech, 'Tech bookmark should be in filtered results');
    const hasMusic = r.body.bookmarks.some(b => b.id === musicBookmarkId);
    assert(!hasMusic, 'Music bookmark should not be in tech filter results');
  });

  await test('REQ-013: Filter case-insensitive → GET /api/bookmarks?tag=TECH', async () => {
    const r = await req('GET', '/api/bookmarks?tag=TECH', null, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    const found = r.body.bookmarks.some(b => b.id === techBookmarkId);
    assert(found, 'Tag filter should be case-insensitive');
  });

  await test('REQ-013: Filter non-existent tag → 200 with empty results', async () => {
    const r = await req('GET', '/api/bookmarks?tag=nonexistent', null, tokenA);
    assert(r.status === 200, `Expected 200, got ${r.status}`);
    const count = r.body.bookmarks.length;
    assert(count === 0, `Expected 0 results for non-existent tag, got ${count}`);
  });
}

// ─── 6. Auth Required Tests ──────────────────────────────────────────────────

async function runAuthRequiredTests() {
  console.log('\n=== AUTH REQUIRED TESTS ===');

  await test('REQ-028: GET /api/bookmarks without token → 401', async () => {
    const r = await req('GET', '/api/bookmarks', null); // no token
    assert(r.status === 401, `Expected 401, got ${r.status}`);
  });

  await test('REQ-028: POST /api/bookmarks without token → 401', async () => {
    const r = await req('POST', '/api/bookmarks', {
      url: 'https://example.com',
      title: 'Test',
    }); // no token
    assert(r.status === 401, `Expected 401, got ${r.status}`);
  });

  await test('REQ-028: PATCH /api/bookmarks/:id without token → 401', async () => {
    const r = await req('PATCH', `/api/bookmarks/${bookmarkA2Id}`, {
      title: 'Hacked',
    }); // no token
    assert(r.status === 401, `Expected 401, got ${r.status}`);
  });

  await test('REQ-028: DELETE /api/bookmarks/:id without token → 401', async () => {
    const r = await req('DELETE', `/api/bookmarks/${bookmarkA2Id}`); // no token
    assert(r.status === 401, `Expected 401, got ${r.status}`);
  });

  await test('REQ-028: Invalid token format → 401', async () => {
    const r = await req('GET', '/api/bookmarks', null, 'invalid-token');
    assert(r.status === 401, `Expected 401, got ${r.status}`);
  });
}

// ─── Main test runner ────────────────────────────────────────────────────────

async function main() {
  console.log('Starting Bookmark API E2E Tests');
  console.log(`Base URL: ${BASE}`);
  console.log('==========================================\n');

  try {
    await runAuthTests();
    await runBookmarkCrudTests();
    await runBusinessRuleTests();
    await runStateMachineTests();
    await runFilterTests();
    await runAuthRequiredTests();

    console.log('\n==========================================');
    console.log(`Total: ${passed + failed} | Passed: ${passed} | Failed: ${failed}`);

    if (failed > 0) {
      console.log('\n=== FAILURES ===');
      results.failed.forEach(item => {
        console.log(`  ✗ ${item.name}`);
        console.log(`    Error: ${item.error}`);
      });
    }

    process.exit(failed > 0 ? 1 : 0);
  } catch (err) {
    console.error('Fatal error:', err);
    process.exit(1);
  }
}

main();
