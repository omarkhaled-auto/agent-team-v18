import { Test, TestingModule } from '@nestjs/testing';
import { UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { JwtStrategy } from './jwt.strategy';
import { UserRepository } from '../../repositories/user.repository';
import { JwtPayload } from '../interfaces/jwt-payload.interface';

describe('JwtStrategy', () => {
  let strategy: JwtStrategy;
  let userRepository: jest.Mocked<UserRepository>;

  const mockUser = {
    id: 'user-uuid-1',
    email: 'test@taskflow.com',
    name: 'Test User',
    passwordHash: 'hashed',
    role: 'MEMBER' as const,
    avatarUrl: null,
    createdAt: new Date(),
    updatedAt: new Date(),
  };

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        JwtStrategy,
        {
          provide: ConfigService,
          useValue: {
            get: jest.fn().mockReturnValue('test-secret'),
          },
        },
        {
          provide: UserRepository,
          useValue: {
            findById: jest.fn(),
          },
        },
      ],
    }).compile();

    strategy = module.get<JwtStrategy>(JwtStrategy);
    userRepository = module.get(UserRepository);
  });

  it('should return payload when user exists', async () => {
    userRepository.findById.mockResolvedValue(mockUser);

    const payload: JwtPayload = {
      sub: 'user-uuid-1',
      email: 'test@taskflow.com',
      role: 'MEMBER',
    };

    const result = await strategy.validate(payload);

    expect(result).toEqual(payload);
    expect(userRepository.findById).toHaveBeenCalledWith('user-uuid-1');
  });

  it('should throw UnauthorizedException when user does not exist', async () => {
    userRepository.findById.mockResolvedValue(null);

    const payload: JwtPayload = {
      sub: 'non-existent-uuid',
      email: 'gone@taskflow.com',
      role: 'MEMBER',
    };

    await expect(strategy.validate(payload)).rejects.toThrow(
      UnauthorizedException,
    );
  });
});
