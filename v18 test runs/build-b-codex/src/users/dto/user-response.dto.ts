import { ApiProperty } from '@nestjs/swagger';
import { UserResponseDto } from '../../common/dto/user.dto';

export class UserTaskStatsDto {
  @ApiProperty()
  assigned!: number;

  @ApiProperty()
  todo!: number;

  @ApiProperty()
  in_progress!: number;

  @ApiProperty()
  in_review!: number;

  @ApiProperty()
  done!: number;
}

export class UserDetailResponseDto extends UserResponseDto {
  @ApiProperty({ type: UserTaskStatsDto })
  taskStats!: UserTaskStatsDto;
}
