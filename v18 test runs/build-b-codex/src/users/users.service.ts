import { Injectable, NotFoundException } from '@nestjs/common';
import { UserResponseDto } from '../common/dto/user.dto';
import { UserDetailResponseDto } from './dto/user-response.dto';
import { UsersRepository } from './users.repository';

@Injectable()
export class UsersService {
  constructor(private readonly usersRepository: UsersRepository) {}

  findAll(): Promise<UserResponseDto[]> {
    return this.usersRepository.findAll();
  }

  async findOne(id: string): Promise<UserDetailResponseDto> {
    const user = await this.usersRepository.findByIdWithStats(id);
    if (!user) {
      throw new NotFoundException('User not found');
    }

    return user;
  }
}
