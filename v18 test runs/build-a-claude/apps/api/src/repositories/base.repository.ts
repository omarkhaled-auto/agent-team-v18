import { PrismaService } from '../prisma/prisma.service';

export abstract class BaseRepository<T> {
  constructor(protected readonly prisma: PrismaService) {}
}
