import {
  Injectable,
  NestInterceptor,
  ExecutionContext,
  CallHandler,
} from '@nestjs/common';
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
export class ResponseInterceptor<T>
  implements NestInterceptor<T, WrappedResponse<T>>
{
  intercept(
    context: ExecutionContext,
    next: CallHandler,
  ): Observable<WrappedResponse<T>> {
    return next.handle().pipe(
      map((responseData) => {
        // If already wrapped (has data + meta), pass through
        if (
          responseData &&
          typeof responseData === 'object' &&
          'data' in responseData &&
          'meta' in responseData
        ) {
          return responseData as WrappedResponse<T>;
        }

        return { data: responseData };
      }),
    );
  }
}
