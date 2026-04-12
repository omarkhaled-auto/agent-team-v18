import {
  HttpException,
  HttpStatus,
  BadRequestException,
  NotFoundException,
  ConflictException,
} from '@nestjs/common';
import { GlobalExceptionFilter } from './http-exception.filter';

describe('GlobalExceptionFilter', () => {
  let filter: GlobalExceptionFilter;
  let mockResponse: any;
  let mockHost: any;

  beforeEach(() => {
    filter = new GlobalExceptionFilter();
    mockResponse = {
      status: jest.fn().mockReturnThis(),
      json: jest.fn().mockReturnThis(),
    };
    mockHost = {
      switchToHttp: () => ({
        getResponse: () => mockResponse,
        getRequest: () => ({ url: '/test' }),
      }),
    };
  });

  it('should format HttpException as { error: { code, message } }', () => {
    const exception = new HttpException('Not allowed', HttpStatus.FORBIDDEN);

    filter.catch(exception, mockHost);

    expect(mockResponse.status).toHaveBeenCalledWith(HttpStatus.FORBIDDEN);
    expect(mockResponse.json).toHaveBeenCalledWith({
      error: {
        code: 'FORBIDDEN',
        message: 'Not allowed',
      },
    });
  });

  it('should handle BadRequestException with validation details', () => {
    const exception = new BadRequestException({
      message: ['email must be an email', 'name should not be empty'],
      error: 'Bad Request',
    });

    filter.catch(exception, mockHost);

    expect(mockResponse.status).toHaveBeenCalledWith(HttpStatus.BAD_REQUEST);
    const jsonCall = mockResponse.json.mock.calls[0][0];
    expect(jsonCall.error.code).toBe('BAD_REQUEST');
  });

  it('should handle NotFoundException', () => {
    const exception = new NotFoundException('Project not found');

    filter.catch(exception, mockHost);

    expect(mockResponse.status).toHaveBeenCalledWith(HttpStatus.NOT_FOUND);
    expect(mockResponse.json).toHaveBeenCalledWith({
      error: {
        code: 'NOT_FOUND',
        message: 'Project not found',
      },
    });
  });

  it('should handle ConflictException', () => {
    const exception = new ConflictException('Email already in use');

    filter.catch(exception, mockHost);

    expect(mockResponse.status).toHaveBeenCalledWith(HttpStatus.CONFLICT);
    expect(mockResponse.json).toHaveBeenCalledWith({
      error: {
        code: 'CONFLICT',
        message: 'Email already in use',
      },
    });
  });

  it('should handle non-HTTP errors as 500 Internal Server Error', () => {
    const exception = new Error('Something broke');

    filter.catch(exception, mockHost);

    expect(mockResponse.status).toHaveBeenCalledWith(
      HttpStatus.INTERNAL_SERVER_ERROR,
    );
    expect(mockResponse.json).toHaveBeenCalledWith({
      error: {
        code: 'INTERNAL_ERROR',
        message: 'Something broke',
      },
    });
  });
});
