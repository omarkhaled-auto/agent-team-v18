import { Bookmark } from "./bookmark.entity";

type CreateBookmarkBody = {
  url: string;
};

type Request<T> = {
  body: T;
};

type Response<T> = {
  json(value: T): T;
};

const bookmarks: Bookmark[] = [
  { id: "1", url: "https://example.com" },
];

const app = {
  post<TReq, TRes>(
    _path: string,
    _handler: (req: Request<TReq>, res: Response<TRes>) => TRes | void,
  ): void {},
  get<TRes>(
    _path: string,
    _handler: (_req: {}, res: Response<TRes>) => TRes | void,
  ): void {},
};

app.post(
  "/api/bookmarks",
  (req: Request<CreateBookmarkBody>, res: Response<Bookmark>) => {
    const created: Bookmark = { id: "2", url: req.body.url };
    bookmarks.push(created);
    return res.json(created);
  },
);

app.get(
  "/api/bookmarks",
  (_req: {}, res: Response<Bookmark[]>) => {
    return res.json(bookmarks);
  },
);

export { app, bookmarks };
