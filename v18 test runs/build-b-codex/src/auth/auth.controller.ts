import { Body, Controller, Get, HttpCode, HttpStatus, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiConflictResponse, ApiOperation, ApiTags, ApiUnauthorizedResponse } from '@nestjs/swagger';
import { CurrentUser, CurrentUserPayload } from '../common/decorators/current-user.decorator';
import { Public } from '../common/decorators/public.decorator';
import { ApiDataResponse } from '../common/swagger/api-data-response.decorator';
import { UserResponseDto } from '../common/dto/user.dto';
import { AuthService } from './auth.service';
import { AuthResponseDto } from './dto/auth-response.dto';
import { LoginDto } from './dto/login.dto';
import { RegisterDto } from './dto/register.dto';

@ApiTags('Auth')
@Controller('auth')
export class AuthController {
  constructor(private readonly authService: AuthService) {}

  @Post('login')
  @Public()
  @HttpCode(HttpStatus.OK)
  @ApiOperation({ summary: 'Login with email and password' })
  @ApiDataResponse(AuthResponseDto, { description: 'Login successful' })
  @ApiUnauthorizedResponse({ description: 'Invalid credentials' })
  async login(@Body() dto: LoginDto): Promise<AuthResponseDto> {
    return this.authService.login(dto);
  }

  @Post('register')
  @Public()
  @HttpCode(HttpStatus.CREATED)
  @ApiOperation({ summary: 'Register a new account' })
  @ApiDataResponse(AuthResponseDto, { description: 'Registration successful', status: 201 })
  @ApiConflictResponse({ description: 'Email already exists' })
  async register(@Body() dto: RegisterDto): Promise<AuthResponseDto> {
    return this.authService.register(dto);
  }

  @Get('me')
  @ApiBearerAuth()
  @ApiOperation({ summary: 'Get current user profile' })
  @ApiDataResponse(UserResponseDto, { description: 'Current user profile' })
  @ApiUnauthorizedResponse({ description: 'Unauthorized' })
  async me(@CurrentUser() user: CurrentUserPayload): Promise<UserResponseDto> {
    return this.authService.getProfile(user.id);
  }
}
