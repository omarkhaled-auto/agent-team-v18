import { Injectable, OnModuleInit, OnModuleDestroy, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Redis from 'ioredis';
import { PrismaService } from '../common/prisma/prisma.service';

export interface AppEvent {
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

@Injectable()
export class EventsService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(EventsService.name);
  private publisher: Redis | null = null;
  private subscriber: Redis | null = null;
  private readonly handlers = new Map<string, Array<(event: AppEvent) => void>>();

  /** Domain handler: updates project timestamp on task events and performs DB writes */
  private readonly taskEventHandler: (event: AppEvent) => void;
  /** Domain handler: soft-deletes tasks when project is archived (DB write) */
  private readonly projectEventHandler: (event: AppEvent) => void;
  /** Domain handler: updates task timestamp when comment is created (DB write) */
  private readonly commentEventHandler: (event: AppEvent) => void;

  constructor(
    private readonly configService: ConfigService,
    private readonly prisma: PrismaService,
  ) {
    // Define domain event handlers that perform real DB writes on domain events.
    // These are bound here so they capture the prisma dependency for business actions.
    this.taskEventHandler = async (event: AppEvent) => {
      if (event.type === 'task.status_changed' || event.type === 'task.created') {
        const { taskId, projectId } = event.payload as { taskId: string; projectId: string };
        await this.prisma.project.update({
          where: { id: projectId },
          data: { updated_at: new Date() },
        });
        this.logger.debug(`Updated project ${projectId} timestamp after task ${taskId} event`);
      }
    };

    this.projectEventHandler = async (event: AppEvent) => {
      if (event.type === 'project.archived') {
        const { projectId } = event.payload as { projectId: string };
        const result = await this.prisma.task.updateMany({
          where: { project_id: projectId, deleted_at: null },
          data: { deleted_at: new Date() },
        });
        this.logger.debug(`Soft-deleted ${result.count} tasks for archived project ${projectId}`);
      }
    };

    this.commentEventHandler = async (event: AppEvent) => {
      if (event.type === 'comment.created') {
        const { taskId } = event.payload as { taskId: string };
        await this.prisma.task.update({
          where: { id: taskId },
          data: { updated_at: new Date() },
        });
        this.logger.debug(`Updated task ${taskId} timestamp after new comment`);
      }
    };

    // Pre-register handler arrays for domain event channels
    this.handlers.set('task.events', [this.taskEventHandler]);
    this.handlers.set('project.events', [this.projectEventHandler]);
    this.handlers.set('comment.events', [this.commentEventHandler]);
  }

  async onModuleInit(): Promise<void> {
    const host = this.configService.get<string>('REDIS_HOST', 'localhost');
    const port = this.configService.get<number>('REDIS_PORT', 6379);

    try {
      this.publisher = new Redis({ host, port, lazyConnect: true, maxRetriesPerRequest: 3 });
      this.subscriber = new Redis({ host, port, lazyConnect: true, maxRetriesPerRequest: 3 });

      await Promise.all([
        this.publisher.connect(),
        this.subscriber.connect(),
      ]);

      this.subscriber.on('message', (channel: string, message: string) => {
        try {
          const event = JSON.parse(message) as AppEvent;
          const channelHandlers = this.handlers.get(channel);
          if (channelHandlers) {
            for (const handler of channelHandlers) {
              handler(event);
            }
          }
        } catch (err) {
          this.logger.error(`Failed to parse event on channel ${channel}`, err);
        }
      });

      this.logger.log('Redis Pub/Sub connected');
    } catch (err) {
      this.logger.warn('Redis connection failed — events will be no-ops', err);
      this.publisher = null;
      this.subscriber = null;
    }

    // Subscribe pre-registered domain handlers to Redis channels
    await this.subscribe('task.events', this.taskEventHandler);
    await this.subscribe('project.events', this.projectEventHandler);
    await this.subscribe('comment.events', this.commentEventHandler);
  }

  async onModuleDestroy(): Promise<void> {
    if (this.subscriber) {
      this.subscriber.disconnect();
    }
    if (this.publisher) {
      this.publisher.disconnect();
    }
    this.logger.log('Redis Pub/Sub disconnected');
  }

  async publish(channel: string, event: Omit<AppEvent, 'timestamp'>): Promise<void> {
    if (!this.publisher) {
      this.logger.debug(`Event dropped (no Redis): ${channel} - ${event.type}`);
      return;
    }

    const fullEvent: AppEvent = {
      ...event,
      timestamp: new Date().toISOString(),
    };

    await this.publisher.publish(channel, JSON.stringify(fullEvent));
    this.logger.debug(`Event published: ${channel} - ${event.type}`);
  }

  async subscribe(channel: string, handler: (event: AppEvent) => void): Promise<void> {
    if (!this.subscriber) {
      this.logger.debug(`Subscribe skipped (no Redis): ${channel}`);
      return;
    }

    if (!this.handlers.has(channel)) {
      this.handlers.set(channel, []);
      await this.subscriber.subscribe(channel);
    }

    this.handlers.get(channel)!.push(handler);
    this.logger.debug(`Subscribed to channel: ${channel}`);
  }
}
