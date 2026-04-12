import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Redis from 'ioredis';

@Injectable()
export class EventsService implements OnModuleDestroy {
  private readonly logger = new Logger(EventsService.name);
  private publisher: Redis | null = null;
  private subscriber: Redis | null = null;
  private connected = false;

  constructor(private readonly config: ConfigService) {
    this.initRedis();
  }

  private initRedis() {
    const host = this.config.get<string>('REDIS_HOST', 'localhost');
    const port = this.config.get<number>('REDIS_PORT', 6379);

    try {
      const redisOptions = {
        host,
        port,
        maxRetriesPerRequest: 3,
        retryStrategy: (times: number) => {
          if (times > 3) {
            this.logger.warn('Redis connection failed after 3 retries — events disabled');
            return null; // stop retrying
          }
          return Math.min(times * 200, 2000);
        },
        lazyConnect: true,
      };

      this.publisher = new Redis(redisOptions);
      this.subscriber = new Redis(redisOptions);

      this.publisher.on('error', (err) => {
        this.logger.warn(`Redis publisher error: ${err.message}`);
        this.connected = false;
      });

      this.subscriber.on('error', (err) => {
        this.logger.warn(`Redis subscriber error: ${err.message}`);
        this.connected = false;
      });

      // Attempt connection without blocking startup
      Promise.all([
        this.publisher.connect(),
        this.subscriber.connect(),
      ])
        .then(() => {
          this.connected = true;
          this.logger.log('Redis connected — events enabled');
        })
        .catch((err) => {
          this.connected = false;
          this.logger.warn(`Redis unavailable — events disabled: ${err.message}`);
        });
    } catch (err) {
      this.logger.warn(`Redis init failed — events disabled: ${err}`);
      this.connected = false;
    }
  }

  async publish(channel: string, message: Record<string, unknown>): Promise<void> {
    if (!this.connected || !this.publisher) {
      this.logger.debug(`Event not published (Redis unavailable): ${channel}`);
      return;
    }
    try {
      await this.publisher.publish(channel, JSON.stringify(message));
    } catch (err) {
      this.logger.warn(`Failed to publish event: ${err}`);
    }
  }

  async subscribe(
    channel: string,
    callback: (message: Record<string, unknown>) => void,
  ): Promise<void> {
    if (!this.connected || !this.subscriber) {
      this.logger.debug(`Cannot subscribe (Redis unavailable): ${channel}`);
      return;
    }
    await this.subscriber.subscribe(channel);
    this.subscriber.on('message', (ch, msg) => {
      if (ch === channel) {
        try {
          callback(JSON.parse(msg));
        } catch {
          this.logger.warn(`Failed to parse message on ${channel}`);
        }
      }
    });
  }

  async onModuleDestroy() {
    await this.publisher?.quit().catch(() => {});
    await this.subscriber?.quit().catch(() => {});
  }
}
