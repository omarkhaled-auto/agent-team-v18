import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module';
import { CommentsController } from './comments.controller';
import { CommentsRepository } from './comments.repository';
import { CommentsService } from './comments.service';

@Module({
  imports: [AuthModule],
  controllers: [CommentsController],
  providers: [CommentsRepository, CommentsService],
  exports: [CommentsRepository, CommentsService],
})
export class CommentsModule {}
