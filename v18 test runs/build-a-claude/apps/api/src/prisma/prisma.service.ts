import { Injectable, OnModuleInit, OnModuleDestroy } from '@nestjs/common';
import { PrismaClient } from '@prisma/client';

const SOFT_DELETE_MODELS = ['Project', 'Task'];

@Injectable()
export class PrismaService extends PrismaClient implements OnModuleInit, OnModuleDestroy {
  async onModuleInit() {
    this.$use(async (params: any, next: any) => {
      if (params.model && SOFT_DELETE_MODELS.includes(params.model)) {
        // Soft-delete: override delete to set deletedAt
        if (params.action === 'delete') {
          params.action = 'update';
          params.args['data'] = { deletedAt: new Date() };
        }
        if (params.action === 'deleteMany') {
          params.action = 'updateMany';
          if (params.args.data !== undefined) {
            params.args.data['deletedAt'] = new Date();
          } else {
            params.args['data'] = { deletedAt: new Date() };
          }
        }

        // Filter out soft-deleted records on reads
        if (params.action === 'findUnique' || params.action === 'findFirst') {
          params.action = 'findFirst';
          if (params.args.where) {
            params.args.where['deletedAt'] = null;
          }
        }
        if (params.action === 'findMany') {
          if (params.args.where) {
            if (params.args.where['deletedAt'] === undefined) {
              params.args.where['deletedAt'] = null;
            }
          } else {
            params.args['where'] = { deletedAt: null };
          }
        }
        if (params.action === 'count') {
          if (params.args.where) {
            if (params.args.where['deletedAt'] === undefined) {
              params.args.where['deletedAt'] = null;
            }
          } else {
            params.args['where'] = { deletedAt: null };
          }
        }
      }
      return next(params);
    });

    await this.$connect();
  }

  async onModuleDestroy() {
    await this.$disconnect();
  }
}
