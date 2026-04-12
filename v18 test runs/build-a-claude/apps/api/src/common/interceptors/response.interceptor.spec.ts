import { ExecutionContext, CallHandler } from '@nestjs/common';
import { of } from 'rxjs';
import { ResponseInterceptor } from './response.interceptor';

describe('ResponseInterceptor', () => {
  let interceptor: ResponseInterceptor<any>;

  beforeEach(() => {
    interceptor = new ResponseInterceptor();
  });

  const mockExecutionContext = {} as ExecutionContext;

  it('should wrap a plain object response in { data }', (done) => {
    const rawData = { id: '1', name: 'Test' };
    const callHandler: CallHandler = { handle: () => of(rawData) };

    interceptor
      .intercept(mockExecutionContext, callHandler)
      .subscribe((result) => {
        expect(result).toEqual({ data: rawData });
        done();
      });
  });

  it('should wrap a string response in { data }', (done) => {
    const callHandler: CallHandler = { handle: () => of('hello') };

    interceptor
      .intercept(mockExecutionContext, callHandler)
      .subscribe((result) => {
        expect(result).toEqual({ data: 'hello' });
        done();
      });
  });

  it('should wrap null response in { data: null }', (done) => {
    const callHandler: CallHandler = { handle: () => of(null) };

    interceptor
      .intercept(mockExecutionContext, callHandler)
      .subscribe((result) => {
        expect(result).toEqual({ data: null });
        done();
      });
  });

  it('should pass through response that already has data property', (done) => {
    const alreadyWrapped = { data: [{ id: 1 }], meta: { total: 1 } };
    const callHandler: CallHandler = { handle: () => of(alreadyWrapped) };

    interceptor
      .intercept(mockExecutionContext, callHandler)
      .subscribe((result) => {
        expect(result).toEqual(alreadyWrapped);
        done();
      });
  });

  it('should wrap an array response in { data }', (done) => {
    const arr = [1, 2, 3];
    const callHandler: CallHandler = { handle: () => of(arr) };

    interceptor
      .intercept(mockExecutionContext, callHandler)
      .subscribe((result) => {
        expect(result).toEqual({ data: arr });
        done();
      });
  });
});
