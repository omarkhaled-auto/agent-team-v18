import { createParamDecorator, ExecutionContext } from '@nestjs/common';
import { UserRole } from '@prisma/client';

export interface CurrentUserPayload {
  id: string;
  email: string;
  role: UserRole;
}

export const CurrentUser = createParamDecorator(
  (data: keyof CurrentUserPayload | undefined, ctx: ExecutionContext): CurrentUserPayload | string => {
    const request = ctx.switchToHttp().getRequest<{ user: CurrentUserPayload }>();
    const user = request.user;
    return data ? user[data] : user;
  },
);
