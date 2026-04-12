import { Test, TestingModule } from '@nestjs/testing';
import { JwtService } from '@nestjs/jwt';
import { UnauthorizedException, ConflictException } from '@nestjs/common';
import * as bcrypt from 'bcrypt';
import { AuthService } from './auth.service';
import { UserRepository } from '../repositories/user.repository';

jest.mock('bcrypt');

describe('AuthService', () => {
  let service: AuthService;
  let userRepository: jest.Mocked<UserRepository>;
  let jwtService: jest.Mocked<JwtService>;

  const mockUser = {
    id: 'user-uuid-1',
    email: 'test@taskflow.com',
    name: 'Test User',
    passwordHash: 'hashed-password',
    role: 'MEMBER' as const,
    avatarUrl: null,
    createdAt: new Date(),
    updatedAt: new Date(),
  };

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        AuthService,
        {
          provide: UserRepository,
          useValue: {
            findByEmail: jest.fn(),
            findById: jest.fn(),
            create: jest.fn(),
          },
        },
        {
          provide: JwtService,
          useValue: {
            sign: jest.fn().mockReturnValue('mock-jwt-token'),
          },
        },
      ],
    }).compile();

    service = module.get<AuthService>(AuthService);
    userRepository = module.get(UserRepository);
    jwtService = module.get(JwtService);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  describe('login', () => {
    it('should return access_token and user for valid credentials', async () => {
      userRepository.findByEmail.mockResolvedValue(mockUser);
      (bcrypt.compare as jest.Mock).mockResolvedValue(true);

      const result = await service.login('test@taskflow.com', 'password123');

      expect(result).toEqual({
        access_token: 'mock-jwt-token',
        user: {
          id: mockUser.id,
          email: mockUser.email,
          name: mockUser.name,
          role: mockUser.role,
        },
      });
      expect(jwtService.sign).toHaveBeenCalledWith({
        sub: mockUser.id,
        email: mockUser.email,
        role: mockUser.role,
      });
    });

    it('should throw UnauthorizedException for non-existent email', async () => {
      userRepository.findByEmail.mockResolvedValue(null);

      await expect(service.login('bad@email.com', 'password')).rejects.toThrow(
        UnauthorizedException,
      );
    });

    it('should throw UnauthorizedException for wrong password', async () => {
      userRepository.findByEmail.mockResolvedValue(mockUser);
      (bcrypt.compare as jest.Mock).mockResolvedValue(false);

      await expect(
        service.login('test@taskflow.com', 'wrong-password'),
      ).rejects.toThrow(UnauthorizedException);
    });

    it('should not reveal whether email exists in error message', async () => {
      userRepository.findByEmail.mockResolvedValue(null);

      try {
        await service.login('bad@email.com', 'password');
      } catch (e) {
        expect(e.message).toBe('Invalid credentials');
      }
    });
  });

  describe('register', () => {
    it('should create user with hashed password and return token', async () => {
      userRepository.findByEmail.mockResolvedValue(null);
      (bcrypt.hash as jest.Mock).mockResolvedValue('hashed-new-password');
      userRepository.create.mockResolvedValue({
        ...mockUser,
        id: 'new-user-uuid',
        passwordHash: 'hashed-new-password',
      });

      const result = await service.register(
        'new@taskflow.com',
        'securePass123',
        'New User',
      );

      expect(bcrypt.hash).toHaveBeenCalledWith('securePass123', 12);
      expect(userRepository.create).toHaveBeenCalledWith({
        email: 'new@taskflow.com',
        name: 'New User',
        passwordHash: 'hashed-new-password',
      });
      expect(result.access_token).toBe('mock-jwt-token');
      expect(result.user).toBeDefined();
    });

    it('should throw ConflictException for duplicate email', async () => {
      userRepository.findByEmail.mockResolvedValue(mockUser);

      await expect(
        service.register('test@taskflow.com', 'password123', 'Test'),
      ).rejects.toThrow(ConflictException);
    });
  });

  describe('getProfile', () => {
    it('should return user profile without password', async () => {
      userRepository.findById.mockResolvedValue(mockUser);

      const result = await service.getProfile('user-uuid-1');

      expect(result).toEqual({
        id: mockUser.id,
        email: mockUser.email,
        name: mockUser.name,
        role: mockUser.role,
      });
      expect(result).not.toHaveProperty('passwordHash');
    });

    it('should throw UnauthorizedException for non-existent user', async () => {
      userRepository.findById.mockResolvedValue(null);

      await expect(service.getProfile('bad-uuid')).rejects.toThrow(
        UnauthorizedException,
      );
    });
  });
});
