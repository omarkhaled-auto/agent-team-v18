import { ConflictException, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { Test } from '@nestjs/testing';
import * as bcrypt from 'bcrypt';
import { AuthRepository } from './auth.repository';
import { AuthService } from './auth.service';

describe('AuthService', () => {
  let authService: AuthService;
  const authRepository = {
    findByEmail: jest.fn(),
    createUser: jest.fn(),
    findProfileById: jest.fn(),
  };
  const jwtService = {
    sign: jest.fn().mockReturnValue('signed-token'),
  };

  beforeEach(async () => {
    jest.clearAllMocks();
    const moduleRef = await Test.createTestingModule({
      providers: [
        AuthService,
        { provide: AuthRepository, useValue: authRepository },
        { provide: JwtService, useValue: jwtService },
      ],
    }).compile();

    authService = moduleRef.get(AuthService);
  });

  it('registers a new user and returns a token', async () => {
    authRepository.findByEmail.mockResolvedValue(null);
    authRepository.createUser.mockResolvedValue({
      id: 'user-1',
      email: 'new@taskflow.com',
      name: 'New User',
      role: 'MEMBER',
    });

    const response = await authService.register({ email: 'new@taskflow.com', name: 'New User', password: 'password123' });
    expect(response).toEqual({
      id: 'user-1',
      email: 'new@taskflow.com',
      name: 'New User',
      role: 'MEMBER',
      access_token: 'signed-token',
    });
    expect(authRepository.createUser).toHaveBeenCalled();
  });

  it('rejects duplicate registrations', async () => {
    authRepository.findByEmail.mockResolvedValue({ id: 'existing-user' });
    await expect(authService.register({ email: 'existing@taskflow.com', name: 'Existing', password: 'password123' })).rejects.toBeInstanceOf(ConflictException);
  });

  it('logs in with valid credentials', async () => {
    const passwordHash = await bcrypt.hash('password123', 1);
    authRepository.findByEmail.mockResolvedValue({
      id: 'user-1',
      email: 'user@taskflow.com',
      name: 'User',
      role: 'MEMBER',
      password_hash: passwordHash,
    });

    await expect(authService.login({ email: 'user@taskflow.com', password: 'password123' })).resolves.toEqual({
      id: 'user-1',
      email: 'user@taskflow.com',
      name: 'User',
      role: 'MEMBER',
      access_token: 'signed-token',
    });
  });

  it('rejects invalid credentials', async () => {
    authRepository.findByEmail.mockResolvedValue(null);
    await expect(authService.login({ email: 'missing@taskflow.com', password: 'password123' })).rejects.toBeInstanceOf(UnauthorizedException);
  });

  it('returns the current profile', async () => {
    authRepository.findProfileById.mockResolvedValue({ id: 'user-1', email: 'user@taskflow.com' });
    await expect(authService.getProfile('user-1')).resolves.toEqual({ id: 'user-1', email: 'user@taskflow.com' });
  });

  it('rejects missing profiles', async () => {
    authRepository.findProfileById.mockResolvedValue(null);
    await expect(authService.getProfile('missing-user')).rejects.toBeInstanceOf(UnauthorizedException);
  });
});
