import {
  ExceptionFilter,
  Catch,
  ArgumentsHost,
  HttpException,
  HttpStatus,
  Logger,
} from '@nestjs/common';
import { Response } from 'express';

@Catch()
export class GlobalExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(GlobalExceptionFilter.name);

  catch(exception: unknown, host: ArgumentsHost): void {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();

    let status = HttpStatus.INTERNAL_SERVER_ERROR;
    let code = 'INTERNAL_SERVER_ERROR';
    let message = 'An unexpected error occurred';
    let details: unknown = undefined;

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      const exceptionResponse = exception.getResponse();

      if (typeof exceptionResponse === 'string') {
        message = exceptionResponse;
      } else if (typeof exceptionResponse === 'object') {
        const res = exceptionResponse as Record<string, unknown>;
        message = (res.message as string) || exception.message;
        if (Array.isArray(res.message)) {
          details = res.message;
          message = 'Validation failed';
        }
      }

      code = this.getErrorCode(status);
    } else if (this.isPrismaError(exception)) {
      const prismaResult = this.handlePrismaError(exception);
      status = prismaResult.status;
      code = prismaResult.code;
      message = prismaResult.message;
    } else {
      this.logger.error(
        'Unhandled exception',
        exception instanceof Error ? exception.stack : String(exception),
      );
    }

    response.status(status).json({
      error: {
        code,
        message,
        ...(details !== undefined && { details }),
      },
    });
  }

  private getErrorCode(status: number): string {
    const codeMap: Record<number, string> = {
      [HttpStatus.BAD_REQUEST]: 'BAD_REQUEST',
      [HttpStatus.UNAUTHORIZED]: 'UNAUTHORIZED',
      [HttpStatus.FORBIDDEN]: 'FORBIDDEN',
      [HttpStatus.NOT_FOUND]: 'NOT_FOUND',
      [HttpStatus.CONFLICT]: 'CONFLICT',
      [HttpStatus.UNPROCESSABLE_ENTITY]: 'UNPROCESSABLE_ENTITY',
      [HttpStatus.TOO_MANY_REQUESTS]: 'TOO_MANY_REQUESTS',
    };
    return codeMap[status] || 'INTERNAL_SERVER_ERROR';
  }

  private isPrismaError(exception: unknown): boolean {
    return (
      typeof exception === 'object' &&
      exception !== null &&
      'code' in exception &&
      typeof (exception as Record<string, unknown>).code === 'string' &&
      (exception as Record<string, unknown>).code
        ?.toString()
        .startsWith('P') === true
    );
  }

  private handlePrismaError(exception: unknown): {
    status: number;
    code: string;
    message: string;
  } {
    const prismaError = exception as { code: string; meta?: Record<string, unknown> };

    switch (prismaError.code) {
      case 'P2002':
        return {
          status: HttpStatus.CONFLICT,
          code: 'DUPLICATE_ENTRY',
          message: `A record with this ${
            (prismaError.meta?.target as string[])?.join(', ') || 'value'
          } already exists`,
        };
      case 'P2025':
        return {
          status: HttpStatus.NOT_FOUND,
          code: 'NOT_FOUND',
          message: 'The requested record was not found',
        };
      case 'P2003':
        return {
          status: HttpStatus.BAD_REQUEST,
          code: 'FOREIGN_KEY_VIOLATION',
          message: 'Referenced record does not exist',
        };
      default:
        return {
          status: HttpStatus.INTERNAL_SERVER_ERROR,
          code: 'DATABASE_ERROR',
          message: 'A database error occurred',
        };
    }
  }
}
