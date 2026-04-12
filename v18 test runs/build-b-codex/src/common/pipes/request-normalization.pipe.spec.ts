import { RequestNormalizationPipe } from './request-normalization.pipe';

describe('RequestNormalizationPipe', () => {
  const pipe = new RequestNormalizationPipe();

  it('normalizes camelCase query params to snake_case aliases', () => {
    expect(pipe.transform({ assigneeId: 'user-1', sortBy: 'priority', sortOrder: 'asc' }, { type: 'query' })).toEqual({
      assignee_id: 'user-1',
      sort: 'priority',
      order: 'asc',
    });
  });

  it('trims query string values', () => {
    expect(pipe.transform({ status: '  ACTIVE  ' }, { type: 'query' })).toEqual({ status: 'ACTIVE' });
  });

  it('drops empty query string values', () => {
    expect(pipe.transform({ status: '   ' }, { type: 'query' })).toEqual({});
  });

  it('converts empty nullable body fields to null', () => {
    expect(pipe.transform({ description: '   ', assigneeId: '   ' }, { type: 'body' })).toEqual({
      description: null,
      assignee_id: null,
    });
  });

  it('preserves empty non-nullable body fields for validation', () => {
    expect(pipe.transform({ title: '   ' }, { type: 'body' })).toEqual({ title: '' });
  });
});
