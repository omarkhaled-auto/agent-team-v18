import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { BaseRepository } from './base.repository';
import { Comment, Prisma } from '@prisma/client';

@Injectable()
export class CommentRepository extends BaseRepository<Comment> {
  constructor(prisma: PrismaService) {
    super(prisma);
  }

  async findAll(params?: {
    skip?: number;
    take?: number;
    where?: Prisma.CommentWhereInput;
    orderBy?: Prisma.CommentOrderByWithRelationInput;
  }): Promise<Comment[]> {
    return this.prisma.comment.findMany({
      ...params,
      include: { author: true },
    });
  }

  async create(data: Prisma.CommentCreateInput): Promise<Comment> {
    return this.prisma.comment.create({ data });
  }

  async count(where?: Prisma.CommentWhereInput): Promise<number> {
    return this.prisma.comment.count({ where });
  }
}
