import { ConflictException, Injectable, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import * as bcrypt from 'bcrypt';
import { AuthResponseDto } from './dto/auth-response.dto';
import { LoginDto } from './dto/login.dto';
import { RegisterDto } from './dto/register.dto';
import { AuthRepository } from './auth.repository';
import { UserResponseDto } from '../common/dto/user.dto';

const BCRYPT_ROUNDS = 10;

@Injectable()
export class AuthService {
  constructor(private readonly authRepository: AuthRepository, private readonly jwtService: JwtService) {}

  async login(dto: LoginDto): Promise<AuthResponseDto> {
    const user = await this.authRepository.findByEmail(dto.email);
    if (!user || !(await bcrypt.compare(dto.password, user.password_hash))) {
      throw new UnauthorizedException('Invalid email or password');
    }

    return this.buildAuthResponse(user.id, user.email, user.name, user.role);
  }

  async register(dto: RegisterDto): Promise<AuthResponseDto> {
    const existingUser = await this.authRepository.findByEmail(dto.email);
    if (existingUser) {
      throw new ConflictException('A user with this email already exists');
    }

    const passwordHash = await bcrypt.hash(dto.password, BCRYPT_ROUNDS);
    const user = await this.authRepository.createUser(dto.email, dto.name, passwordHash);
    return this.buildAuthResponse(user.id, user.email, user.name, user.role);
  }

  async getProfile(userId: string): Promise<UserResponseDto> {
    const user = await this.authRepository.findProfileById(userId);
    if (!user) {
      throw new UnauthorizedException('User not found');
    }

    return user;
  }

  private buildAuthResponse(id: string, email: string, name: string, role: AuthResponseDto['role']): AuthResponseDto {
    const access_token = this.jwtService.sign({ sub: id, email, role });
    return { id, email, name, role, access_token };
  }
}
