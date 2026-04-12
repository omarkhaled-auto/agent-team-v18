import { ArgumentMetadata, Injectable, PipeTransform } from '@nestjs/common';

type NormalizationMode = 'body' | 'query';

const KEY_ALIASES: Record<string, string> = {
  sort_by: 'sort',
  sortBy: 'sort',
  sort_order: 'order',
  sortOrder: 'order',
};

const NULLABLE_BODY_FIELDS = new Set(['description', 'due_date', 'assignee_id', 'avatar_url']);

@Injectable()
export class RequestNormalizationPipe implements PipeTransform {
  transform(value: unknown, metadata: ArgumentMetadata): unknown {
    if (metadata.type !== 'body' && metadata.type !== 'query') {
      return value;
    }

    return normalizeValue(value, metadata.type);
  }
}

function normalizeValue(value: unknown, mode: NormalizationMode, parentKey?: string): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeValue(item, mode, parentKey));
  }

  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).reduce<Record<string, unknown>>((accumulator, [key, entryValue]) => {
      const normalizedKey = normalizeKey(key);
      const normalizedValue = normalizeValue(entryValue, mode, normalizedKey);

      if (normalizedValue === undefined && mode === 'query') {
        return accumulator;
      }

      if (!(normalizedKey in accumulator)) {
        accumulator[normalizedKey] = normalizedValue;
      }

      return accumulator;
    }, {});
  }

  if (typeof value !== 'string') {
    return value;
  }

  if (parentKey?.toLowerCase().includes('password')) {
    return value;
  }

  const trimmed = value.trim();
  if (trimmed.length > 0) {
    return trimmed;
  }

  if (mode === 'query') {
    return undefined;
  }

  if (parentKey && NULLABLE_BODY_FIELDS.has(parentKey)) {
    return null;
  }

  return trimmed;
}

function normalizeKey(key: string): string {
  const snakeKey = key.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
  return KEY_ALIASES[key] ?? KEY_ALIASES[snakeKey] ?? snakeKey;
}
