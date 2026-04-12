import { ArgumentsHost, Catch, ExceptionFilter, HttpException, HttpStatus, Logger } from '@nestjs/common';
import { Response } from 'express';

@Catch()
export class GlobalExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(GlobalExceptionFilter.name);

  catch(exception: unknown, host: ArgumentsHost): void {
    const response = host.switchToHttp().getResponse<Response>();

    let status = HttpStatus.INTERNAL_SERVER_ERROR;
    let code = 'INTERNAL_SERVER_ERROR';
    let message = 'An unexpected error occurred';
    let details: unknown;

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      code = getErrorCode(status);

      const exceptionResponse = exception.getResponse();
      if (typeof exceptionResponse === 'string') {
        message = exceptionResponse;
      } else if (typeof exceptionResponse === 'object' && exceptionResponse) {
        const payload = exceptionResponse as Record<string, unknown>;
        if (Array.isArray(payload.message)) {
          code = 'VALIDATION_ERROR';
          message = 'Validation failed';
          details = payload.message;
        } else {
          message = (payload.message as string) || exception.message;
        }

        if (typeof payload.code === 'string') {
          code = payload.code;
        }

        if (payload.details !== undefined) {
          details = payload.details;
        }
      }
    } else if (isPrismaError(exception)) {
      const prismaError = mapPrismaError(exception as { code: string });
      status = prismaError.status;
      code = prismaError.code;
      message = prismaError.message;
    } else {
      this.logger.error('Unhandled exception', exception instanceof Error ? exception.stack : String(exception));
    }

    response.status(status).json({
      error: {
        code,
        message,
        ...(details !== undefined ? { details } : {}),
      },
    });
  }
}

function getErrorCode(status: number): string {
  const codes: Record<number, string> = {
    [HttpStatus.BAD_REQUEST]: 'BAD_REQUEST',
    [HttpStatus.UNAUTHORIZED]: 'UNAUTHORIZED',
    [HttpStatus.FORBIDDEN]: 'FORBIDDEN',
    [HttpStatus.NOT_FOUND]: 'NOT_FOUND',
    [HttpStatus.CONFLICT]: 'CONFLICT',
  };

  return codes[status] || 'INTERNAL_SERVER_ERROR';
}

function isPrismaError(exception: unknown): boolean {
  return (
    typeof exception === 'object' &&
    exception !== null &&
    'code' in exception &&
    typeof (exception as Record<string, unknown>).code === 'string' &&
    (exception as Record<string, string>).code.startsWith('P')
  );
}

function mapPrismaError(exception: { code: string }): { status: number; code: string; message: string } {
  switch (exception.code) {
    case 'P2002':
      return { status: HttpStatus.CONFLICT, code: 'CONFLICT', message: 'A record with this value already exists' };
    case 'P2025':
      return { status: HttpStatus.NOT_FOUND, code: 'NOT_FOUND', message: 'The requested record was not found' };
    case 'P2003':
      return { status: HttpStatus.BAD_REQUEST, code: 'BAD_REQUEST', message: 'Referenced record does not exist' };
    default:
      return { status: HttpStatus.INTERNAL_SERVER_ERROR, code: 'INTERNAL_SERVER_ERROR', message: 'A database error occurred' };
  }
}
