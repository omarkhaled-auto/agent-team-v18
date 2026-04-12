import { NextRequest, NextResponse } from 'next/server';

import { defaultLocale, getLocaleFromPath, localeHeader } from './src/i18n/locales';

const PUBLIC_FILE_PATTERN = /\.[^/]+$/;

export function middleware(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;

  if (pathname.startsWith('/_next') || PUBLIC_FILE_PATTERN.test(pathname)) {
    return NextResponse.next();
  }

  const pathnameLocale = getLocaleFromPath(pathname);

  if (!pathnameLocale) {
    const normalizedPath = pathname === '/' ? '' : pathname;
    const redirectUrl = new URL(`/${defaultLocale}${normalizedPath}${search}`, request.url);
    return NextResponse.redirect(redirectUrl);
  }

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(localeHeader, pathnameLocale);

  return NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
