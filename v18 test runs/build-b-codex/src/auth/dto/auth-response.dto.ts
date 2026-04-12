import { ApiProperty } from '@nestjs/swagger';
import { UserRole } from '@prisma/client';

export class AuthResponseDto {
  @ApiProperty()
  id!: string;

  @ApiProperty()
  email!: string;

  @ApiProperty()
  name!: string;

  @ApiProperty({ enum: UserRole })
  role!: UserRole;

  @ApiProperty()
  access_token!: string;
}
