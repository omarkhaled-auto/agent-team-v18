import { Type, applyDecorators } from '@nestjs/common';
import { ApiCreatedResponse, ApiExtraModels, ApiOkResponse, getSchemaPath } from '@nestjs/swagger';
import { PaginationMetaDto } from '../dto/pagination.dto';

interface ApiDataResponseOptions {
  description: string;
  status?: 200 | 201;
  isArray?: boolean;
  paginated?: boolean;
}

export function ApiDataResponse(model: Type<unknown>, options: ApiDataResponseOptions): MethodDecorator {
  const { description, status = 200, isArray = false, paginated = false } = options;
  const successDecorator = status === 201 ? ApiCreatedResponse : ApiOkResponse;

  return applyDecorators(
    ApiExtraModels(model, PaginationMetaDto),
    successDecorator({
      description,
      schema: {
        type: 'object',
        properties: {
          data: isArray
            ? { type: 'array', items: { $ref: getSchemaPath(model) } }
            : { $ref: getSchemaPath(model) },
          ...(paginated ? { meta: { $ref: getSchemaPath(PaginationMetaDto) } } : {}),
        },
      },
    }),
  );
}
