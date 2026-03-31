# ArkanPM API Contract Audit Report
**Modules:** Owner + Dashboard + Documents + Cross-Cutting  
**Date:** 2026-03-31  
**Scope:** Frontend-Backend API Contract Mismatches

---

## MISMATCH 1: OWNER UNITS API RESPONSE WRAPPING
**Severity: HIGH**

**Frontend file:** `apps/web/src/app/(dashboard)/owner/units/page.tsx` (line 15-16)  
**Backend file:** `apps/api/src/owner/owner-dashboard.service.ts` (line 199)

**Issue:**
```typescript
// Frontend: tries to handle both wrapped and bare array
const res = await api.get<any>('/owner/units');
setUnits(Array.isArray(res) ? res : res.data ?? []);

// Backend: ALWAYS returns wrapped
return { data: enriched, meta: { total: enriched.length } };
```

Frontend expects either bare array OR `{data}` wrapper. Backend **always** wraps. The fallback logic in frontend suggests inconsistency in API contract across different endpoints.

**Fix:** Frontend should consistently expect wrapped response:
```typescript
const res = await api.get<any>('/owner/units');
setUnits(res?.data ?? []);  // Always expect { data, meta } wrapper
```

---

## MISMATCH 2: DOCUMENT FIELD NAME INCONSISTENCIES
**Severity: MEDIUM**

**Frontend file:** `apps/web/src/app/(dashboard)/documents/page.tsx` (line 49-60)  
**Backend file:** `apps/api/src/document/document.service.ts` (line 226-230)

**Issue:**
Frontend maps document fields with fallback chains:
```typescript
name: d.name || d.title || '-',
uploadedBy: d.uploader_name || d.uploaded_by || d.uploadedBy || '-',
uploadedAt: d.uploaded_at || d.uploadedAt || d.created_at || '',
fileType: d.file_type || d.mime_type?.split('/').pop() || d.fileType || '-',
fileSize: d.file_size || d.fileSize || 0,
```

Backend returns (DocumentService.findAll):
- `uploader_name` ✓ (enriched field)
- `entity_name` ✓ (enriched field)  
- All other fields: snake_case (`file_name`, `file_size`, `mime_type`, `created_at`)

**Problems:**
1. Frontend checks for `name` but backend has `title`
2. Frontend checks camelCase variants (`uploadedBy`, `fileType`, `fileSize`) but backend returns snake_case
3. These fallback chains indicate historic API inconsistency

**Fix:** Standardize on snake_case throughout, OR create frontend DTO mapper:
```typescript
// Backend returns
const d = { title, file_size, uploaded_at, mime_type, uploader_name, ... }

// Frontend should map once
const mapped = {
  name: d.title,
  fileSize: d.file_size,
  uploadedAt: d.uploaded_at,
  uploadedBy: d.uploader_name,
}
```

---

## MISMATCH 3: AUTH USER SHAPE - JWT ROLES vs USER INTERFACE
**Severity: HIGH**

**Frontend file:** `apps/web/src/lib/auth-context.tsx` (line 40-50)  
**Backend file:** `apps/api/src/auth/auth.service.ts` (line 350-360, 563-567)

**Issue:**
Backend JWT payload contains:
```typescript
// auth.service.ts line 563-567
const payload = {
  sub: userId,
  email,
  tenantId,
  roles: string[],  // ← ARRAY
};
```

Backend getProfile returns:
```typescript
// auth.service.ts line 349-361
return {
  id, email,
  firstName, lastName, displayName,
  tenantId,
  roles: string[],  // ← ARRAY
  mfaEnabled, lastLoginAt, status
}
```

Frontend User interface expects:
```typescript
// auth-context.tsx line 6-14
export interface User {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: string;  // ← SINGLE STRING, not array!
  organizationId: string;
}
```

Frontend conversion shows the mismatch:
```typescript
// auth-context.tsx line 40-50
const role = Array.isArray(raw.roles) ? raw.roles[0] : raw.role || '';

// Later: dashboard.tsx line 91-94
const role = user?.role?.toLowerCase() || '';
if (role === 'owner') ...  // Expects single string
```

**Breaking problem:** Frontend loses permission info by converting `roles[]` → `role: string`. Dashboard role checks only use first role, ignoring additional roles.

**Fix:** Either:
1. Backend returns `role: string` (first role only) in JWT + getProfile, OR
2. Frontend User interface should have `roles: string[]` and update all role checks

---

## MISMATCH 4: OWNER PROFILE RESPONSE - NESTING INCONSISTENCY
**Severity: MEDIUM**

**Frontend file:** `apps/web/src/app/(dashboard)/owner/profile/page.tsx` (line 28-29, 93)  
**Backend file:** `apps/api/src/owner/owner-dashboard.service.ts` (line 93-106)

**Issue:**
Backend returns:
```typescript
// getProfile
return {
  ...owner,  // spreads all owner fields (id, email, phone, etc.)
  user: { id, email, first_name, last_name, phone } || null
}
// NOT wrapped in { data }
```

Frontend expects:
```typescript
const res = await api.get<any>('/owner/profile');
const data = res?.data ?? res;  // handles both wrapped and unwrapped
setProfile(data);
// Later accesses
profile?.email || profile?.user?.email || '-'
profile?.phone  // from spread
profile?.user?.first_name  // from nested user?
```

**Problems:**
1. Backend spreads owner fields but also includes nested `user` object (redundant)
2. `/owner/profile` doesn't wrap in `{data}` but `/owner/units` does → inconsistent
3. Email, name, phone exist in both owner and user objects

**Fix:** Consistent wrapping or consistent spreading, not both:
```typescript
// Option A: Wrap all endpoints
return { data: { ...owner, user }, meta: {} }

// Option B: No nesting
return { ...owner, userEmail: user?.email }
```

---

## MISMATCH 5: DASHBOARD API - INCONSISTENT PAGINATION RESPONSE SHAPES
**Severity: MEDIUM**

**Frontend file:** `apps/web/src/app/(dashboard)/dashboard/page.tsx` (line 97-106, 108, 117-118)  
**Backend:** Multiple controllers

**Issue:**
Dashboard makes parallel API calls expecting different response shapes:
```typescript
const woRes = api.get<any>('/work-orders', { params: { limit: 1 } });
// Expected: { data, meta: { total } }
// Access: woRes.value?.meta?.total

const maintDashRes = api.get<any>('/maintenance-dashboard');
// Expected: bare object { sla_compliance_percent, ... }
// Access: maintDashRes.value?.sla_compliance_percent (NO meta)

const unitsRes = api.get<any>('/units', { params: { limit: 100 } });
// Expected: { data }
// Access: unitsRes.value?.data
```

**Problems:**
1. `/maintenance-dashboard` returns bare object, not `{ data, meta }`
2. `/work-orders` returns `{ data, meta }`
3. No consistent pagination format
4. Frontend treats them differently

**Fix:** All list endpoints should return `{ data: T[], meta: { total, page, limit, totalPages } }` consistently.

---

## MISMATCH 6: OWNER DASHBOARD RESPONSE STRUCTURE
**Severity: LOW (Note: This one MATCHES, but document others don't)**

**Frontend file:** `apps/web/src/app/(dashboard)/owner/page.tsx` (line 32-33)  
**Backend file:** `apps/api/src/owner/owner-dashboard.service.ts` (line 81-91)

**Status:** ✓ **MATCHES** (unusual for this audit)

Frontend expects:
```typescript
interface DashboardData {
  owner: { id, display_name, type } | null;
  stats: { totalUnits, occupiedUnits, vacantUnits, monthlyIncome };
  upcomingExpirations: Array<{ lease_id, lease_number, unit_name, end_date, monthly_rent }>;
}
```

Backend returns exactly that structure.

**Note:** Backend returns unwrapped (not `{ data: DashboardData, meta }`), which is inconsistent with other endpoints.

---

## MISMATCH 7: DOCUMENT CATEGORIES ENDPOINT NOT FOUND
**Severity: MEDIUM**

**Frontend file:** `apps/web/src/app/(dashboard)/documents/page.tsx` (line 42-46)  
**Backend:** NOT FOUND

**Issue:**
Frontend calls:
```typescript
const catRes = api.get('/document-categories');
```

Expected response:
```typescript
// Frontend Category interface (lines 8-13)
interface Category {
  id: string;
  name: string;
  children?: Category[];
  count: number;
}
```

**Problem:** No `GET /document-categories` endpoint found in codebase. File `document-category.controller.ts` exists but doesn't expose this endpoint. Frontend will receive 404 or unexpected response.

**Fix:** Implement `/document-categories` endpoint in DocumentCategoryController or correct frontend API call.

---

## MISMATCH 8: API RESPONSE WRAPPER - SYSTEM-WIDE INCONSISTENCY
**Severity: HIGH (Cross-cutting)**

**Frontend file:** `apps/web/src/lib/api.ts` (line 87)  
**Backend:** All controllers

**Issue:**
Frontend has no response normalization layer:
```typescript
// api.ts line 87
return res.json();  // Raw response, no unwrapping
```

Across codebase, different endpoints return different shapes:

| Endpoint | Response Format | Frontend Handler |
|----------|-----------------|------------------|
| `/owner/units` | `{ data, meta }` | `res.data \|\| res` |
| `/owner/dashboard` | `{ owner, stats, ... }` | Direct `res` |
| `/owner/profile` | Spread owner object | `res.data \|\| res` |
| `/documents` | `{ data, meta }` | `res.data \|\| res` |
| `/maintenance-dashboard` | Bare object | `res.sla_compliance...` |
| `/auth/me` | Spread user fields | Direct `res` |

**Frontend defensive programming:**
```typescript
// Pattern 1: Ambiguous
setUnits(Array.isArray(res) ? res : res.data ?? []);

// Pattern 2: Unwrap once
const data = res?.data ?? res;

// Pattern 3: Direct access
setData(res);  // expects unwrapped
```

**Root cause:** No consistent API response wrapper format. Some endpoints wrap in `{ data, meta }`, others return bare objects.

**Fix:** Implement ONE of:
1. **Standardize backend:** All endpoints return `{ data: T, meta: { ... } }`
2. **Standardize frontend:** Create response normalizer function:
   ```typescript
   function normalizeResponse<T>(res: any): { data: T; meta?: any } {
     if (res?.data !== undefined) return res;  // Already wrapped
     if (Array.isArray(res)) return { data: res };  // Bare array
     return { data: res };  // Bare object
   }
   ```

---

## MISMATCH 9: OWNER DASHBOARD getMyUnits PAGINATION META
**Severity: MEDIUM**

**Frontend file:** `apps/web/src/app/(dashboard)/owner/units/page.tsx` (line 15-16)  
**Backend file:** `apps/api/src/owner/owner-dashboard.service.ts` (line 199)

**Issue:**
Backend returns:
```typescript
return { data: enriched, meta: { total: enriched.length } };
```

Only includes `total` in meta, missing standard pagination fields:
- `page` (not included)
- `limit` (not included)
- `totalPages` (not included)

Frontend expectations (inferred from other code):
```typescript
docRes?.meta?.totalPages  // Will be undefined for owner/units
```

**Fix:** Return complete pagination meta:
```typescript
return {
  data: enriched,
  meta: {
    total: enriched.length,
    page: 1,
    limit: enriched.length,
    totalPages: 1
  }
};
```

---

## SUMMARY TABLE

| # | Module | Severity | Issue | Impact |
|---|--------|----------|-------|--------|
| 1 | Owner Units | HIGH | Inconsistent response wrapping | Fragile frontend code |
| 2 | Documents | MEDIUM | Field name mismatches (snake_case vs camelCase) | Document library display issues |
| 3 | Auth | HIGH | JWT roles[] vs User interface role: string | Role-based logic failures |
| 4 | Owner Profile | MEDIUM | Spread + nested object pattern | Unclear API contract |
| 5 | Dashboard | MEDIUM | Inconsistent pagination format | Multiple response shape handling |
| 6 | Owner Dashboard | LOW | ✓ Matches (documented for consistency) | None |
| 7 | Documents | MEDIUM | Categories endpoint missing | 404 errors on documents page |
| 8 | Cross-cutting | HIGH | No consistent response wrapper | System-wide brittleness |
| 9 | Owner Units | MEDIUM | Incomplete pagination meta | Missing totalPages, page, limit |

---

## SEVERITY BREAKDOWN

- **HIGH (3):** Auth user shape, Response wrapper inconsistency, Owner units wrapping
- **MEDIUM (5):** Document fields, Dashboard pagination, Owner profile, Categories, Pagination meta
- **LOW (1):** Marked for awareness only

---

## KEY PATTERNS IDENTIFIED

1. **Field Naming**: snake_case backend ↔ camelCase frontend (inconsistent mapping)
2. **Response Format**: Some wrap `{ data, meta }`, others return bare objects
3. **Array vs Single**: JWT has `roles[]` but User interface expects `role: string`
4. **Nesting**: Inconsistent use of spread vs nested objects
5. **Pagination Meta**: Missing standard fields (page, limit, totalPages)
6. **Missing Endpoints**: `/document-categories` not found

---

## RECOMMENDATIONS (Priority Order)

1. **CRITICAL:** Standardize all API responses to `{ data: T[], meta: { total, page, limit, totalPages } }`
   - Fixes: Mismatches 1, 5, 8, 9

2. **CRITICAL:** Fix auth user shape - standardize on single `role: string` or handle `roles[]` properly
   - Fixes: Mismatch 3

3. **HIGH:** Implement missing document-categories endpoint
   - Fixes: Mismatch 7

4. **HIGH:** Create frontend response normalizer to handle shape inconsistencies
   - Fixes: Mismatch 8

5. **MEDIUM:** Standardize field naming (snake_case throughout)
   - Fixes: Mismatch 2

6. **MEDIUM:** Consistent response nesting pattern (spread OR nested, not both)
   - Fixes: Mismatch 4

---

## AFFECTED MODULES

- **Owner Module:** 4 mismatches (units wrapping, profile nesting, dashboard pagination, pagination meta)
- **Dashboard Module:** 2 mismatches (response shape, pagination format)
- **Documents Module:** 2 mismatches (field names, categories missing)
- **Cross-Cutting:** 1 mismatch (response wrapper system-wide)
- **Auth:** 1 mismatch (user shape)

---

**Report Generated:** 2026-03-31  
**Status:** RESEARCH ONLY - No files modified
