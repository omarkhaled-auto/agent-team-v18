import { CallHandler, ExecutionContext, Injectable, NestInterceptor } from '@nestjs/common';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

export interface WrappedResponse<T> {
  data: T;
  meta?: {
    total: number;
    page: number;
    limit: number;
  };
}

@Injectable()
export class ResponseInterceptor<T> implements NestInterceptor<T, WrappedResponse<T>> {
  intercept(_context: ExecutionContext, next: CallHandler): Observable<WrappedResponse<T>> {
    return next.handle().pipe(
      map((responseData) => {
        const serialized = serializeValue(responseData);
        if (serialized && typeof serialized === 'object' && 'data' in serialized) {
          return serialized as WrappedResponse<T>;
        }

        return { data: serialized as T };
      }),
    );
  }
}

function serializeValue(value: unknown): unknown {
  if (value instanceof Date) {
    return value.toISOString();
  }

  if (Array.isArray(value)) {
    return value.map((item) => serializeValue(item));
  }

  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).reduce<Record<string, unknown>>((accumulator, [key, entryValue]) => {
      if (entryValue !== undefined) {
        accumulator[key] = serializeValue(entryValue);
      }

      return accumulator;
    }, {});
  }

  return value;
}
