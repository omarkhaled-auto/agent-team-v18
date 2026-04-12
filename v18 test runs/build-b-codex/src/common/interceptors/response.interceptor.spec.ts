import { CallHandler, ExecutionContext } from '@nestjs/common';
import { of } from 'rxjs';
import { ResponseInterceptor } from './response.interceptor';

describe('ResponseInterceptor', () => {
  const interceptor = new ResponseInterceptor();
  const context = {} as ExecutionContext;

  it('wraps plain responses in a data envelope', (done) => {
    const next = { handle: () => of({ ok: true }) } as CallHandler;
    interceptor.intercept(context, next).subscribe((value) => {
      expect(value).toEqual({ data: { ok: true } });
      done();
    });
  });

  it('preserves pre-wrapped paginated responses', (done) => {
    const next = { handle: () => of({ data: [{ id: '1' }], meta: { total: 1, page: 1, limit: 20 } }) } as CallHandler;
    interceptor.intercept(context, next).subscribe((value) => {
      expect(value).toEqual({ data: [{ id: '1' }], meta: { total: 1, page: 1, limit: 20 } });
      done();
    });
  });

  it('serializes nested dates to ISO strings', (done) => {
    const next = { handle: () => of({ created_at: new Date('2026-04-12T00:00:00.000Z') }) } as CallHandler;
    interceptor.intercept(context, next).subscribe((value) => {
      expect(value).toEqual({ data: { created_at: '2026-04-12T00:00:00.000Z' } });
      done();
    });
  });
});
