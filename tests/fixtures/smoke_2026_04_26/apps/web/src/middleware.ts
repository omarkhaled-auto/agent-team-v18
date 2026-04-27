// SCAFFOLD STUB — Wave D finalizes with JWT cookie forwarding.
import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

export function middleware(_request: NextRequest): NextResponse {
  return NextResponse.next();
}

export const config = {
  matcher: [],
};
