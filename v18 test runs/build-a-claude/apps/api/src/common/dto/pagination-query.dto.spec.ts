import { validate } from 'class-validator';
import { plainToInstance } from 'class-transformer';
import { PaginationQueryDto } from './pagination-query.dto';

describe('PaginationQueryDto', () => {
  function toDto(data: Record<string, unknown>): PaginationQueryDto {
    return plainToInstance(PaginationQueryDto, data);
  }

  it('should have correct defaults when no input is provided', () => {
    const dto = toDto({});
    expect(dto.page).toBe(1);
    expect(dto.limit).toBe(20);
  });

  it('should accept valid page and limit', async () => {
    const dto = toDto({ page: 3, limit: 50 });
    const errors = await validate(dto);
    expect(errors.length).toBe(0);
    expect(dto.page).toBe(3);
    expect(dto.limit).toBe(50);
  });

  it('should reject page less than 1', async () => {
    const dto = toDto({ page: 0 });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
    const pageError = errors.find((e) => e.property === 'page');
    expect(pageError).toBeDefined();
  });

  it('should reject negative page', async () => {
    const dto = toDto({ page: -5 });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
  });

  it('should reject limit greater than 100', async () => {
    const dto = toDto({ limit: 200 });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
    const limitError = errors.find((e) => e.property === 'limit');
    expect(limitError).toBeDefined();
  });

  it('should reject limit less than 1', async () => {
    const dto = toDto({ limit: 0 });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
  });

  it('should accept limit of exactly 100', async () => {
    const dto = toDto({ limit: 100 });
    const errors = await validate(dto);
    expect(errors.length).toBe(0);
  });

  it('should accept limit of exactly 1', async () => {
    const dto = toDto({ limit: 1 });
    const errors = await validate(dto);
    expect(errors.length).toBe(0);
  });
});
