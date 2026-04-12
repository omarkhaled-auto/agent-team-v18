import { Controller, Get, Param, ParseUUIDPipe } from '@nestjs/common';
import { ApiBearerAuth, ApiNotFoundResponse, ApiOperation, ApiTags } from '@nestjs/swagger';
import { UserResponseDto } from '../common/dto/user.dto';
import { ApiDataResponse } from '../common/swagger/api-data-response.decorator';
import { UserDetailResponseDto } from './dto/user-response.dto';
import { UsersService } from './users.service';

@ApiTags('Users')
@ApiBearerAuth()
@Controller('users')
export class UsersController {
  constructor(private readonly usersService: UsersService) {}

  @Get()
  @ApiOperation({ summary: 'List all users' })
  @ApiDataResponse(UserResponseDto, { description: 'List of users', isArray: true })
  async findAll(): Promise<UserResponseDto[]> {
    return this.usersService.findAll();
  }

  @Get(':id')
  @ApiOperation({ summary: 'Get a user profile with task stats' })
  @ApiDataResponse(UserDetailResponseDto, { description: 'User profile with task stats' })
  @ApiNotFoundResponse({ description: 'User not found' })
  async findOne(@Param('id', ParseUUIDPipe) id: string): Promise<UserDetailResponseDto> {
    return this.usersService.findOne(id);
  }
}
