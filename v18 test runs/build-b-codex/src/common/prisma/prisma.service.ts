import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { Prisma, PrismaClient } from '@prisma/client';

@Injectable()
export class PrismaService extends PrismaClient implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(PrismaService.name);

  constructor() {
    super();

    this.$use(async (params, next) => {
      if (params.model !== 'Task') {
        return next(params);
      }

      if (
        params.action === 'findFirst' ||
        params.action === 'findMany' ||
        params.action === 'count' ||
        params.action === 'aggregate' ||
        params.action === 'groupBy'
      ) {
        params.args = withSoftDeleteFilter(params.args);
      }

      return next(params);
    });
  }

  async onModuleInit(): Promise<void> {
    await this.$connect();
    this.logger.log('Connected to database');
  }

  async onModuleDestroy(): Promise<void> {
    await this.$disconnect();
    this.logger.log('Disconnected from database');
  }
}

function withSoftDeleteFilter<T extends Prisma.MiddlewareParams['args']>(args: T): T {
  const nextArgs = (args ?? {}) as Record<string, unknown>;
  const currentWhere = (nextArgs.where ?? {}) as Record<string, unknown>;

  if (currentWhere.deleted_at !== undefined) {
    return nextArgs as T;
  }

  return {
    ...nextArgs,
    where: {
      ...currentWhere,
      deleted_at: null,
    },
  } as T;
}
