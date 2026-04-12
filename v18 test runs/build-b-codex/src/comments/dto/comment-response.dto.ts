import { ApiProperty } from '@nestjs/swagger';
import { UserSummaryDto } from '../../common/dto/user.dto';

export class CommentResponseDto {
  @ApiProperty()
  id!: string;

  @ApiProperty()
  content!: string;

  @ApiProperty()
  task_id!: string;

  @ApiProperty()
  author_id!: string;

  @ApiProperty({ type: UserSummaryDto })
  author!: UserSummaryDto;

  @ApiProperty()
  created_at!: string;
}
