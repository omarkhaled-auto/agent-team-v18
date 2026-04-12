import { CanActivate, ExecutionContext, ForbiddenException, Injectable, UnauthorizedException } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { UserRole } from '@prisma/client';
import { CurrentUserPayload } from '../../common/decorators/current-user.decorator';
import { ROLES_KEY } from '../../common/decorators/roles.decorator';

@Injectable()
export class RolesGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const requiredRoles = this.reflector.getAllAndOverride<UserRole[]>(ROLES_KEY, [context.getHandler(), context.getClass()]);
    if (!requiredRoles?.length) {
      return true;
    }

    const request = context.switchToHttp().getRequest<{ user?: CurrentUserPayload }>();
    if (!request.user) {
      throw new UnauthorizedException('Authentication required');
    }

    if (!requiredRoles.includes(request.user.role)) {
      throw new ForbiddenException('Insufficient permissions');
    }

    return true;
  }
}
