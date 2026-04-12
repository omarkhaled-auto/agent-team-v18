import { Injectable } from '@nestjs/common';
import { UserRole } from '@prisma/client';
import { PrismaService } from '../common/prisma/prisma.service';
import { mapUser } from '../common/utils/response-mappers';
import { UserResponseDto } from '../common/dto/user.dto';

interface UserWithPassword {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  avatar_url: string | null;
  password_hash: string;
  created_at: Date;
  updated_at: Date;
}

@Injectable()
export class AuthRepository {
  constructor(private readonly prisma: PrismaService) {}

  async findByEmail(email: string): Promise<UserWithPassword | null> {
    return this.prisma.user.findUnique({
      where: { email },
      select: {
        id: true,
        email: true,
        name: true,
        role: true,
        avatar_url: true,
        password_hash: true,
        created_at: true,
        updated_at: true,
      },
    });
  }

  async createUser(email: string, name: string, passwordHash: string): Promise<UserWithPassword> {
    return this.prisma.user.create({
      data: {
        email,
        name,
        password_hash: passwordHash,
      },
      select: {
        id: true,
        email: true,
        name: true,
        role: true,
        avatar_url: true,
        password_hash: true,
        created_at: true,
        updated_at: true,
      },
    });
  }

  async findProfileById(userId: string): Promise<UserResponseDto | null> {
    const user = await this.prisma.user.findUnique({
      where: { id: userId },
      select: {
        id: true,
        email: true,
        name: true,
        role: true,
        avatar_url: true,
        created_at: true,
        updated_at: true,
      },
    });

    return user ? mapUser(user) : null;
  }

  async findAuthUserById(userId: string): Promise<{ id: string; email: string; role: UserRole } | null> {
    return this.prisma.user.findUnique({
      where: { id: userId },
      select: {
        id: true,
        email: true,
        role: true,
      },
    });
  }
}
